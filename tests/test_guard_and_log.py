import asyncio
import time

import pytest

from chat_window.guard import AnswerGate, Busy, RateLimiter
from chat_window.logstore import ChatLog, redact


def test_rate_limits_per_minute_and_day():
    limiter, now = RateLimiter(), 1_000_000.0
    assert all(limiter.check("v", 3, 5, now + i) is None for i in range(3))
    assert "wait a minute" in limiter.check("v", 3, 5, now + 3)
    assert limiter.check("other", 3, 5, now + 3) is None          # per visitor
    assert limiter.check("v", 3, 5, now + 70) is None
    assert limiter.check("v", 3, 5, now + 71) is None
    assert "today's limit" in limiter.check("v", 3, 5, now + 140)
    assert limiter.check("v", 3, 5, now + 86400 + 80) is None      # a day later


def test_answer_gate_queues_then_refuses():
    async def run():
        gate = AnswerGate(concurrent=1, queue=1)
        release = asyncio.Event()

        async def hold():
            async with gate:
                await release.wait()
        first = asyncio.create_task(hold())
        await asyncio.sleep(0)
        second = asyncio.create_task(hold())                          # waits in the queue
        await asyncio.sleep(0)
        with pytest.raises(Busy):
            async with gate:
                pass
        release.set()
        await asyncio.gather(first, second)
    asyncio.run(run())


def test_log_needs_a_secret(tmp_path):
    with pytest.raises(ValueError):
        ChatLog(tmp_path / "c.sqlite", "")


def test_log_hashes_addresses_and_honours_retention(tmp_path):
    log = ChatLog(tmp_path / "c.sqlite", "s3cret")
    log.record(site="a", session="s1", address="203.0.113.9", question="hi", answer="hello", outcome="answered")
    log.record(site="b", session="s2", address="203.0.113.9", question="hi", outcome="answered")
    row = log.db.execute("SELECT visitor FROM chats WHERE site='a'").fetchone()[0]
    assert "203.0.113" not in row and len(row) == 16
    assert row != log.db.execute("SELECT visitor FROM chats WHERE site='b'").fetchone()[0]   # not linkable across sites
    assert log.purge({"a": 30, "b": 1}, now=time.time() + 2 * 86400) == 1
    assert log.purge({"a": 30}, now=time.time() + 31 * 86400) == 1
    assert log.db.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 0


def test_deleting_a_session_removes_its_rows(tmp_path):
    log = ChatLog(tmp_path / "c.sqlite", "k")
    for session in ("s1", "s1", "s2"):
        log.record(site="a", session=session, address="x", question="q", outcome="answered")
    assert log.delete_session("a", "s1") == 2
    assert log.delete_session("other", "s2") == 0
    assert log.db.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 1


def test_export_is_redacted_and_leaves_out_identifiers(tmp_path):
    log = ChatLog(tmp_path / "c.sqlite", "k")
    log.record(site="a", session="s1", address="x", outcome="answered",
               question="I'm jo@example.com, call +1 (313) 555-0199 from 198.51.100.4",
               answer="token ab12cd34ef56gh78ij90kl12mn34 noted")
    log.record(site="a", session="s1", address="x", question="spam", outcome="rate_limited")
    rows = list(log.export("a"))
    assert len(rows) == 1 and set(rows[0]) == {"ts", "question", "answer", "sources", "outcome"}
    assert rows[0]["question"] == "I'm [email], call [phone] from [address]"
    assert rows[0]["answer"] == "token [token] noted"


def test_redact_keeps_ordinary_numbers():
    assert redact("The $40.00 plan has 8 GB and 160GB NVMe") == "The $40.00 plan has 8 GB and 160GB NVMe"
