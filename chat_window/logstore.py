"""The chat log: kept `retention_days` (30 by default), then deleted.

Visitor addresses are never stored; a keyed hash lets abuse from one address be seen
across a site's log without keeping the address. Deleting a session (the chat window's
"Delete this chat") removes its rows at once.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY, site TEXT NOT NULL, session TEXT NOT NULL, ts INTEGER NOT NULL,
    visitor TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]', outcome TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
    first_token_ms INTEGER, total_ms INTEGER
);
CREATE INDEX IF NOT EXISTS chats_site_ts ON chats (site, ts);
CREATE INDEX IF NOT EXISTS chats_session ON chats (session);
"""

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
IP = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b|\b[0-9a-f]{1,4}(:[0-9a-f]{0,4}){3,7}\b", re.I)
SECRETISH = re.compile(r"\b(?=\w*\d)(?=\w*[a-zA-Z])\w{24,}\b")


def redact(text: str) -> str:
    """Remove the obvious personal details before a log leaves the server for review or training."""
    text = EMAIL.sub("[email]", text)
    text = IP.sub("[address]", text)
    text = PHONE.sub("[phone]", text)
    return SECRETISH.sub("[token]", text)


class ChatLog:
    def __init__(self, path: Path, secret: str):
        if not secret:
            raise ValueError("CHAT_WINDOW_SECRET must be set: it keys the hashed visitor addresses")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        try:
            path.chmod(0o600)             # only the service account reads the log
        except PermissionError:           # opened by another account (e.g. root reading stats)
            pass
        self.db.executescript(SCHEMA)
        self.secret = secret.encode()
        self.lock = threading.Lock()

    def visitor(self, address: str, site: str) -> str:
        return hmac.new(self.secret, f"{site}\0{address}".encode(), hashlib.sha256).hexdigest()[:16]

    def record(self, *, site: str, session: str, address: str, question: str, answer: str = "",
               sources: list | None = None, outcome: str, model: str = "",
               first_token_ms: int | None = None, total_ms: int | None = None) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO chats (site,session,ts,visitor,question,answer,sources,outcome,model,"
                "first_token_ms,total_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (site, session, int(time.time()), self.visitor(address, site), question[:4000], answer[:8000],
                 json.dumps(sources or []), outcome, model, first_token_ms, total_ms))
            self.db.commit()

    def delete_session(self, site: str, session: str) -> int:
        with self.lock:
            n = self.db.execute("DELETE FROM chats WHERE site=? AND session=?", (site, session)).rowcount
            self.db.commit()
            return n

    def purge(self, retention_days: dict[str, int], default_days: int = 30, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        with self.lock:
            sites = [r[0] for r in self.db.execute("SELECT DISTINCT site FROM chats")]
            for site in sites:
                cutoff = int(now - retention_days.get(site, default_days) * 86400)
                removed += self.db.execute("DELETE FROM chats WHERE site=? AND ts<?", (site, cutoff)).rowcount
            self.db.commit()
        return removed

    def stats(self, site: str, days: int = 7) -> dict:
        since = int(time.time() - days * 86400)
        rows = self.db.execute(
            "SELECT outcome, COUNT(*) FROM chats WHERE site=? AND ts>=? GROUP BY outcome", (site, since)).fetchall()
        times = [r[0] for r in self.db.execute(
            "SELECT first_token_ms FROM chats WHERE site=? AND ts>=? AND first_token_ms IS NOT NULL "
            "ORDER BY first_token_ms", (site, since))]
        uncovered = [r[0] for r in self.db.execute(
            "SELECT question FROM chats WHERE site=? AND ts>=? AND outcome='not_covered' ORDER BY ts DESC LIMIT 25",
            (site, since))]
        visitors = self.db.execute(
            "SELECT COUNT(DISTINCT visitor) FROM chats WHERE site=? AND ts>=?", (site, since)).fetchone()[0]

        def pct(p):
            return times[min(len(times) - 1, int(p * len(times)))] if times else None
        return {"days": days, "outcomes": dict(rows), "visitors": visitors,
                "first_token_ms": {"p50": pct(0.5), "p95": pct(0.95)}, "recent_not_covered": uncovered}

    def export(self, site: str, days: int | None = None):
        """Redacted rows for review or training. Visitor hashes and sessions are left out."""
        since = int(time.time() - days * 86400) if days else 0
        for ts, question, answer, sources, outcome in self.db.execute(
                "SELECT ts,question,answer,sources,outcome FROM chats WHERE site=? AND ts>=? AND outcome IN "
                "('answered','not_covered') ORDER BY ts", (site, since)):
            yield {"ts": ts, "question": redact(question), "answer": redact(answer),
                   "sources": json.loads(sources), "outcome": outcome}
