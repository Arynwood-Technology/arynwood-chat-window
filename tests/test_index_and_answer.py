import asyncio
import os
import time

import pytest

from chat_window import answer
from chat_window.index import Index, build
from chat_window.textify import Chunk

from .conftest import make_site

CHUNKS = [
    Chunk("https://demo.example/pricing", "Pricing", "Plans", "The small plan costs $4.00 a month."),
    Chunk("https://demo.example/shipping", "Shipping", "Abroad", "We ship widgets to 30 countries."),
    Chunk("https://demo.example/about", "About", "", "Demo Co. was founded in Detroit."),
]
VECTORS = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "index.sqlite"
    build(path, CHUNKS, VECTORS, {"site": "demo"})
    return Index(path)


def test_vector_and_keyword_rankings_are_fused(index):
    hits = index.search("how much is the small plan", [0.9, 0.1, 0.0], top_k=2)
    assert hits[0].url == "https://demo.example/pricing"
    assert hits[0].similarity > 0.9
    assert index.meta["chunk_count"] == 3 and index.meta["dim"] == 3


def test_keyword_only_search_works_without_vectors(index):
    hits = index.search("ship countries", None, top_k=3)
    assert hits and hits[0].url == "https://demo.example/shipping" and hits[0].similarity == 0.0


def test_odd_questions_do_not_break_the_keyword_query(index):
    assert index.search('"" AND OR NEAR(', [0, 0, 1], top_k=1)[0].url == "https://demo.example/about"


def test_rebuild_is_atomic_and_detected(index, tmp_path):
    path = tmp_path / "index.sqlite"
    assert not index.stale()
    build(path, CHUNKS[:1], VECTORS[:1], {"site": "demo"})
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert index.stale()
    assert not list(tmp_path.glob("*.building"))


@pytest.mark.parametrize("url,ok", [
    ("https://demo.example/a", True), ("https://shop.demo.example/a", True), ("http://demo.example", True),
    ("https://evildemo.example/a", False), ("https://demo.example.evil.net/", False),
    ("javascript:alert(1)", False), ("https://user@evil.net/demo.example", False),
])
def test_host_allowed(url, ok):
    assert answer.host_allowed(url, ("demo.example",)) is ok


def test_offsite_links_become_plain_text():
    text = ("See [plans](https://demo.example/pricing) or [this](https://evil.net/x), "
            "https://demo.example/faq and https://evil.net/y.")
    out = answer.strip_offsite_links(text, ("demo.example",))
    assert "[plans](https://demo.example/pricing)" in out and "https://demo.example/faq" in out
    assert "evil.net" not in out and "this" in out


def test_follow_ups_borrow_the_previous_question():
    history = [("What does the small plan cost?", "$4.00 a month.")]
    assert answer.retrieval_query("and storage?", history).startswith("What does the small plan cost?")
    assert answer.retrieval_query("how much is it?", history).startswith("What does the small plan cost?")
    assert answer.retrieval_query("What's the weather in Seattle?", history) == "What's the weather in Seattle?"
    assert answer.retrieval_query("Tell me everything about shipping widgets abroad please", history) \
        == "Tell me everything about shipping widgets abroad please"


def test_prompt_frames_excerpts_as_untrusted_and_trims_history():
    site = make_site()
    from chat_window.index import Hit
    hits = [Hit(1, "https://demo.example/pricing", "Pricing", "Plans", "Small: $4.00", 1.0, 0.9)]
    history = [("q" * 900, "a" * 900)] * 10
    messages = answer.build_messages(site, "How much?", hits, history)
    assert messages[0]["role"] == "system" and "Demo Co." in messages[0]["content"]
    last = messages[-1]["content"]
    assert last.startswith('<untrusted-data source="website excerpts">') and "Visitor question: How much?" in last
    assert "URL: https://demo.example/pricing" in last
    assert sum(len(m["content"]) for m in messages[1:-1]) <= 2400


def test_uncovered_questions_never_reach_the_model(monkeypatch):
    site = make_site()

    async def boom(*a, **k):
        raise AssertionError("model called")
        yield  # pragma: no cover

    monkeypatch.setattr(answer.ollama, "chat_stream", boom)

    async def run():
        return [p async for p in answer.stream_answer(site, "weather?", answer.Retrieved([], False), [])]
    reply = "".join(asyncio.run(run()))
    assert "couldn't find" in reply and site.contact in reply
