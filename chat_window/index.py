"""One SQLite file per site: pages, chunks, an FTS5 keyword index and stored embeddings.

Built into a temporary file and swapped in with os.replace, so a running server never
sees a half-built index. Search fuses keyword (bm25) and vector rankings by rank.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .textify import Chunk

STOPWORDS = set("""a an and are as at be but by can do does for from has have how i if in is it its me my
of on or our so than that the their them there these they this to was we what when where which who why
will with you your about into just more not any all also get got""".split())


@dataclass
class Hit:
    id: int
    url: str
    title: str
    heading: str
    text: str
    score: float          # fused rank score, for ordering
    similarity: float     # cosine similarity to the question (0 when it only matched by keyword)


def build(path: Path, chunks: list[Chunk], vectors: list[list[float]], meta: dict) -> None:
    if len(chunks) != len(vectors):
        raise ValueError("one vector per chunk")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    try:
        db.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE chunks (id INTEGER PRIMARY KEY, url TEXT, title TEXT, heading TEXT, text TEXT,
                                 embedding BLOB);
            CREATE VIRTUAL TABLE chunks_fts USING fts5(title, heading, text, content='chunks',
                                                       content_rowid='id', tokenize='porter unicode61');
        """)
        for chunk, vector in zip(chunks, vectors):
            v = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(v)) or 1.0
            db.execute("INSERT INTO chunks (url,title,heading,text,embedding) VALUES (?,?,?,?,?)",
                       (chunk.url, chunk.title, chunk.heading, chunk.text, (v / norm).tobytes()))
        db.execute("INSERT INTO chunks_fts (chunks_fts) VALUES ('rebuild')")
        meta = {**meta, "chunk_count": len(chunks), "built_at": int(time.time()),
                "dim": len(vectors[0]) if vectors else 0}
        db.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
        db.commit()
    finally:
        db.close()
    os.replace(tmp, path)


def _fts_query(question: str) -> str:
    words = [w for w in re.findall(r"\w+", question.lower()) if w not in STOPWORDS and len(w) > 1]
    return " OR ".join('"' + w.replace('"', '') + '"' for w in dict.fromkeys(words))[:2000]


class Index:
    """A loaded, read-only index. Cheap to reload when the file changes."""

    def __init__(self, path: Path):
        self.path = path
        self.mtime = path.stat().st_mtime
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.meta = {k: json.loads(v) for k, v in self.db.execute("SELECT key,value FROM meta")}
        rows = self.db.execute("SELECT id, embedding FROM chunks ORDER BY id").fetchall()
        self.ids = np.array([r[0] for r in rows], dtype=np.int64)
        dim = int(self.meta.get("dim") or 0)
        self.matrix = (np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), dim)
                       if rows and dim else np.zeros((0, max(dim, 1)), dtype=np.float32))

    def stale(self) -> bool:
        try:
            return self.path.stat().st_mtime != self.mtime
        except FileNotFoundError:
            return False

    def close(self) -> None:
        self.db.close()

    def _rows(self, ids: list[int]) -> dict[int, tuple]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {r[0]: r for r in self.db.execute(
            f"SELECT id,url,title,heading,text FROM chunks WHERE id IN ({marks})", ids)}

    def search(self, question: str, query_vector: list[float] | None, top_k: int = 4,
               pool: int = 20) -> list[Hit]:
        ranked: list[list[int]] = []
        sims: dict[int, float] = {}
        if query_vector is not None and len(self.ids):
            q = np.asarray(query_vector, dtype=np.float32)
            q /= float(np.linalg.norm(q)) or 1.0
            scores = self.matrix @ q
            order = np.argsort(-scores)[:pool]
            ranked.append([int(self.ids[i]) for i in order])
            sims = {int(self.ids[i]): float(scores[i]) for i in order}
        match = _fts_query(question)
        if match:
            try:
                ranked.append([r[0] for r in self.db.execute(
                    "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts, 4.0, 2.0, 1.0) "
                    "LIMIT ?", (match, pool))])
            except sqlite3.OperationalError:
                pass
        fused: dict[int, float] = {}
        for ranking in ranked:
            for rank, cid in enumerate(ranking):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank)
        best = sorted(fused, key=fused.get, reverse=True)[:top_k]
        rows = self._rows(best)
        if query_vector is not None:
            missing = [cid for cid in best if cid not in sims]
            for cid in missing:
                pos = int(np.searchsorted(self.ids, cid))
                q = np.asarray(query_vector, dtype=np.float32)
                sims[cid] = float(self.matrix[pos] @ (q / (float(np.linalg.norm(q)) or 1.0)))
        return [Hit(cid, *rows[cid][1:], score=fused[cid], similarity=sims.get(cid, 0.0))
                for cid in best if cid in rows]
