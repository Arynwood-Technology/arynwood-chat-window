"""Abuse limits: per-visitor rate limits and a cap on concurrent answers.

In memory, per process. One model on one machine is the expected deployment; a restart
resets the counters, which errs toward letting people ask.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    def __init__(self) -> None:
        self.recent: dict[str, deque[float]] = {}

    def check(self, key: str, per_minute: int, per_day: int, now: float | None = None) -> str | None:
        """Record a request; return None if allowed, else a reason the visitor can read."""
        now = time.time() if now is None else now
        q = self.recent.setdefault(key, deque())
        while q and now - q[0] > 86400:
            q.popleft()
        if len(q) >= per_day:
            return "You've reached today's limit for this chat. Please try again tomorrow."
        if sum(1 for t in q if now - t < 60) >= per_minute:
            return "That's a lot of questions at once. Please wait a minute and try again."
        q.append(now)
        if len(self.recent) > 50_000:
            self._sweep(now)
        return None

    def _sweep(self, now: float) -> None:
        for key in [k for k, q in self.recent.items() if not q or now - q[-1] > 86400]:
            del self.recent[key]


class Busy(Exception):
    pass


class AnswerGate:
    """At most `concurrent` answers generate at once; at most `queue` more wait."""

    def __init__(self, concurrent: int, queue: int) -> None:
        self.semaphore = asyncio.Semaphore(max(1, concurrent))
        self.queue = max(0, queue)
        self.waiting = 0

    async def __aenter__(self):
        if self.semaphore.locked() and self.waiting >= self.queue:
            raise Busy()
        self.waiting += 1
        try:
            await self.semaphore.acquire()
        finally:
            self.waiting -= 1
        return self

    async def __aexit__(self, *exc):
        self.semaphore.release()
