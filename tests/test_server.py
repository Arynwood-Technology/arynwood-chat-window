import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chat_window import answer, server
from chat_window.config import ConfigError, Settings, parse_networks
from chat_window.index import Hit, build
from chat_window.textify import Chunk

from .conftest import make_site

ORIGIN = {"Origin": "https://demo.example"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    site = make_site(limits={"per_minute": 3, "per_day": 10, "max_message_chars": 50})
    settings = Settings(sites_dir=tmp_path, data_dir=tmp_path / "data", secret="k",
                        trusted_proxies=parse_networks("127.0.0.0/8"), client_ip_header="X-Real-IP",
                        max_concurrent=1, max_queue=2)
    build(settings.site_dir("demo") / "index.sqlite",
          [Chunk("https://demo.example/plans", "Plans", "", "Small: $4.00")], [[1.0, 0.0]], {"site": "demo"})

    async def retrieve(site, index, message, history):
        covered = "weather" not in message
        return answer.Retrieved([Hit(1, "https://demo.example/plans", "Plans", "", "Small: $4.00", 1, 0.9)], covered)

    async def chat_stream(messages, *a, **k):
        assert messages[-1]["content"].startswith("<untrusted-data")
        for piece in ("The small plan ", "is $4.00."):
            yield piece

    async def ready(self, site):
        return True

    monkeypatch.setattr(answer, "retrieve", retrieve)
    monkeypatch.setattr(answer.ollama, "chat_stream", chat_stream)
    monkeypatch.setattr(server.State, "models_ready", ready)
    app = server.create_app(settings, {"demo": site})
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        c.chat_state = app.state.chat
        yield c


def events(response):
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_site_info_refuses_foreign_origins(client):
    assert client.get("/v1/sites/demo").status_code == 200       # same-origin GETs carry no Origin
    assert client.get("/v1/sites/demo", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/v1/sites/nope", headers=ORIGIN).status_code == 404
    r = client.get("/v1/sites/demo", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["available"] is True
    assert r.headers["access-control-allow-origin"] == "https://demo.example"
    assert "description" not in r.json()


def test_preflight(client):
    ok = client.options("/v1/chat", headers={**ORIGIN, "Access-Control-Request-Method": "POST"})
    assert ok.status_code == 204 and ok.headers["access-control-allow-origin"] == "https://demo.example"
    assert client.options("/v1/chat", headers={"Origin": "https://evil.example"}).status_code == 403


def test_chat_streams_session_sources_tokens_done_and_logs(client):
    r = client.post("/v1/chat", json={"site": "demo", "message": "  How much   is it? "},
                    headers={**ORIGIN, "X-Real-IP": "198.51.100.7"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = events(r)
    assert [e for e, _ in got] == ["session", "sources", "token", "token", "done"]
    assert got[1][1] == [{"title": "Plans", "url": "https://demo.example/plans"}]
    assert got[-1][1] == {"outcome": "answered"}
    row = client.chat_state.log.db.execute("SELECT question, answer, outcome, visitor FROM chats").fetchone()
    assert row[:3] == ("How much is it?", "The small plan is $4.00.", "answered")
    assert row[3] == client.chat_state.log.visitor("198.51.100.7", "demo")


def test_follow_up_keeps_the_session_and_delete_forgets_it(client):
    first = events(client.post("/v1/chat", json={"site": "demo", "message": "price?"}, headers=ORIGIN))
    session = first[0][1]["session"]
    again = events(client.post("/v1/chat", json={"site": "demo", "message": "and more?", "session": session},
                               headers=ORIGIN))
    assert again[0][1]["session"] == session
    assert len(client.chat_state.sessions[session].history) == 2
    assert client.delete(f"/v1/sessions/{session}?site=demo").status_code == 403
    r = client.delete(f"/v1/sessions/{session}?site=demo", headers=ORIGIN)
    assert r.json() == {"deleted": 2} and session not in client.chat_state.sessions


def test_uncovered_question_gets_the_handoff_without_sources(client):
    got = events(client.post("/v1/chat", json={"site": "demo", "message": "weather tomorrow?"}, headers=ORIGIN))
    assert got[1] == ("sources", [])
    assert "couldn't find" in "".join(d["t"] for e, d in got if e == "token")
    assert got[-1][1] == {"outcome": "not_covered"}


def test_bad_requests(client):
    assert client.post("/v1/chat", content="nope", headers=ORIGIN).status_code == 400
    assert client.post("/v1/chat", json=["x"], headers=ORIGIN).status_code == 400
    assert client.post("/v1/chat", json={"site": "demo", "message": "   "}, headers=ORIGIN).status_code == 400
    assert client.post("/v1/chat", json={"site": "demo", "message": "x" * 51}, headers=ORIGIN).status_code == 413
    assert client.post("/v1/chat", json={"site": "demo", "message": "hi"}).status_code == 403


def test_rate_limit_is_per_visitor_and_logged(client):
    for _ in range(3):
        assert client.post("/v1/chat", json={"site": "demo", "message": "hi"},
                           headers={**ORIGIN, "X-Real-IP": "192.0.2.1"}).status_code == 200
    r = client.post("/v1/chat", json={"site": "demo", "message": "hi"}, headers={**ORIGIN, "X-Real-IP": "192.0.2.1"})
    assert r.status_code == 429 and "wait a minute" in r.json()["error"]
    assert client.post("/v1/chat", json={"site": "demo", "message": "hi"},
                       headers={**ORIGIN, "X-Real-IP": "192.0.2.2"}).status_code == 200
    outcomes = [r[0] for r in client.chat_state.log.db.execute("SELECT outcome FROM chats")]
    assert outcomes.count("rate_limited") == 1


def test_client_address_header_is_only_trusted_from_proxies():
    settings = Settings(Path("."), Path("."), "k", parse_networks("127.0.0.1, 10.20.0.0/16, ::1"), "X-Real-IP", 1, 1)

    class Req:
        def __init__(self, peer, header):
            self.client = type("C", (), {"host": peer})()
            self.headers = {"X-Real-IP": header} if header else {}
    assert server.client_address(Req("127.0.0.1", "198.51.100.1"), settings) == "198.51.100.1"
    assert server.client_address(Req("203.0.113.5", "198.51.100.1"), settings) == "203.0.113.5"
    assert server.client_address(Req("127.0.0.1", ""), settings) == "127.0.0.1"
    assert server.client_address(Req("10.20.3.4", "198.51.100.2"), settings) == "198.51.100.2"   # a proxy on the LAN
    assert server.client_address(Req("10.21.0.1", "198.51.100.2"), settings) == "10.21.0.1"
    assert server.client_address(Req("testclient", "198.51.100.2"), settings) == "testclient"
    with pytest.raises(ConfigError):
        parse_networks("127.0.0.1, not-an-ip")


def test_api_responses_are_never_cached(client):
    assert client.get("/v1/sites/demo", headers=ORIGIN).headers["cache-control"] == "no-store"
    assert client.get("/v1/health").headers["cache-control"] == "no-store"
    assert "max-age" in client.get("/chat-window.js").headers["cache-control"]


def test_widget_is_served_as_javascript(client):
    r = client.get("/chat-window.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert r.headers["x-content-type-options"] == "nosniff"
