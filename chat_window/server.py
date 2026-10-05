"""The chat window's web server.

    GET    /v1/sites/{site}        what the chat window shows (name, greeting, notice) + availability
    POST   /v1/chat                {site, message, session?} -> text/event-stream
    DELETE /v1/sessions/{session}  ?site=  forget a chat and delete its log rows
    GET    /v1/health
    GET    /chat-window.js         the chat window itself

Only browsers on a site's `allowed_origins` are answered. No cookies, no accounts.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from . import answer, ollama
from .config import Settings, Site
from .guard import AnswerGate, Busy, RateLimiter
from .index import Index
from .logstore import ChatLog

STATIC = Path(__file__).parent / "static"
SESSION_TTL = 1800
MAX_SESSIONS = 10_000


@dataclass
class Session:
    site: str
    history: list[tuple[str, str]] = field(default_factory=list)
    seen: float = field(default_factory=time.time)


class State:
    def __init__(self, settings: Settings, sites: dict[str, Site]):
        self.settings = settings
        self.sites = sites
        self.indexes: dict[str, Index] = {}
        self.limiter = RateLimiter()
        self.gate = AnswerGate(settings.max_concurrent, settings.max_queue)
        self.log = ChatLog(settings.data_dir / "chats.sqlite", settings.secret)
        self.sessions: dict[str, Session] = {}
        self.model_ok: dict[tuple[str, str], tuple[float, bool]] = {}
        self.origins = {o for s in sites.values() for o in s.allowed_origins}

    def index(self, site_id: str) -> Index | None:
        current = self.indexes.get(site_id)
        if current and not current.stale():
            return current
        path = self.settings.site_dir(site_id) / "index.sqlite"
        if not path.exists():
            return current
        fresh = Index(path)
        self.indexes[site_id] = fresh
        if current:
            current.close()
        return fresh

    async def models_ready(self, site: Site) -> bool:
        key = (site.model.ollama_url, site.model.chat)
        cached = self.model_ok.get(key)
        if cached and time.time() - cached[0] < 30:
            return cached[1]
        ok = all((await ollama.available(site.model.ollama_url, [site.model.chat, site.model.embed])).values())
        self.model_ok[key] = (time.time(), ok)
        return ok

    def session(self, site_id: str, session_id: str | None) -> tuple[str, Session]:
        now = time.time()
        if len(self.sessions) > MAX_SESSIONS:
            for key in sorted(self.sessions, key=lambda k: self.sessions[k].seen)[:len(self.sessions) // 10]:
                del self.sessions[key]
        found = self.sessions.get(session_id or "")
        if found and found.site == site_id and now - found.seen < SESSION_TTL:
            found.seen = now
            return session_id, found
        new_id = secrets.token_urlsafe(18)
        self.sessions[new_id] = Session(site_id)
        return new_id, self.sessions[new_id]


def client_address(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client else ""
    if settings.trusts(peer):
        forwarded = request.headers.get(settings.client_ip_header, "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None, sites: dict[str, Site] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    sites = settings.load_sites() if sites is None else sites
    state = State(settings, sites)

    async def purge_forever():
        while True:
            state.log.purge({s.id: s.retention_days for s in state.sites.values()})
            await asyncio.sleep(3600)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(purge_forever())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="Arynwood Chat Window", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.chat = state

    @app.middleware("http")
    async def cors(request: Request, call_next):
        origin = request.headers.get("origin", "")
        allowed = origin.lower() in state.origins
        if request.method == "OPTIONS":
            if not allowed:
                return Response(status_code=403)
            return Response(status_code=204, headers={
                "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, POST, DELETE",
                "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600",
                "Vary": "Origin"})
        response = await call_next(request)
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"     # never let a CDN cache an answer or a site's status
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def site_for(request: Request, site_id: str) -> Site | JSONResponse:
        site = state.sites.get(site_id)
        if not site:
            return JSONResponse({"error": "Unknown site."}, status_code=404)
        if request.headers.get("origin", "").lower() not in site.allowed_origins:
            return JSONResponse({"error": "This chat isn't enabled for this website."}, status_code=403)
        return site

    @app.get("/v1/health")
    async def health():
        return {"ok": True, "sites": len(state.sites)}

    @app.get("/chat-window.js")
    async def widget():
        return FileResponse(STATIC / "chat-window.js", media_type="application/javascript",
                            headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/v1/sites/{site_id}")
    async def site_info(site_id: str, request: Request):
        site = site_for(request, site_id)
        if isinstance(site, JSONResponse):
            return site
        available = state.index(site.id) is not None and await state.models_ready(site)
        return {**site.public(), "available": available}

    @app.delete("/v1/sessions/{session_id}")
    async def delete_session(session_id: str, site: str, request: Request):
        found = site_for(request, site)
        if isinstance(found, JSONResponse):
            return found
        held = state.sessions.get(session_id)
        if held and held.site == found.id:
            del state.sessions[session_id]
        deleted = state.log.delete_session(found.id, session_id)
        return {"deleted": deleted}

    @app.post("/v1/chat")
    async def chat(request: Request):
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "Send JSON."}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Send a JSON object."}, status_code=400)
        site = site_for(request, str(body.get("site", "")))
        if isinstance(site, JSONResponse):
            return site
        message = " ".join(str(body.get("message", "")).split())
        if not message:
            return JSONResponse({"error": "Type a question first."}, status_code=400)
        if len(message) > site.limits.max_message_chars:
            return JSONResponse({"error": f"Please keep questions under {site.limits.max_message_chars} "
                                          "characters."}, status_code=413)
        address = client_address(request, settings)
        session_id, session = state.session(site.id, body.get("session"))
        if len(session.history) >= site.limits.max_turns * 3:
            return JSONResponse({"error": "This chat is long. Start a new one to keep going."}, status_code=429)
        refusal = state.limiter.check(f"{site.id}\0{address}", site.limits.per_minute, site.limits.per_day)
        if refusal:
            state.log.record(site=site.id, session=session_id, address=address, question=message,
                             outcome="rate_limited")
            return JSONResponse({"error": refusal}, status_code=429)
        index = state.index(site.id)
        if index is None:
            return JSONResponse({"error": "This chat isn't ready yet."}, status_code=503)
        if state.gate.semaphore.locked() and state.gate.waiting >= state.gate.queue:
            state.log.record(site=site.id, session=session_id, address=address, question=message, outcome="busy")
            return JSONResponse({"error": "The assistant is busy. Please try again in a minute."}, status_code=503)

        async def events():
            started = time.monotonic()
            reply, outcome, sources, first_ms = [], "error", [], None
            try:
                yield sse("session", {"session": session_id})
                async with state.gate:
                    retrieved = await answer.retrieve(site, index, message, session.history)
                    sources = retrieved.sources() if retrieved.covered else []
                    yield sse("sources", sources)
                    async for piece in answer.stream_answer(site, message, retrieved, session.history):
                        if first_ms is None:
                            first_ms = int((time.monotonic() - started) * 1000)
                        reply.append(piece)
                        yield sse("token", {"t": piece})
                outcome = "answered" if retrieved.covered else "not_covered"
                text = "".join(reply).strip()
                session.history.append((message, text))
                yield sse("done", {"outcome": outcome})
            except Busy:
                outcome = "busy"
                yield sse("error", {"message": "The assistant is busy. Please try again in a minute."})
            except ollama.ModelError:
                yield sse("error", {"message": "The assistant is unavailable right now. Please try again later."})
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            finally:
                state.log.record(site=site.id, session=session_id, address=address, question=message,
                                 answer="".join(reply), sources=sources, outcome=outcome, model=site.model.chat,
                                 first_token_ms=first_ms, total_ms=int((time.monotonic() - started) * 1000))

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return app
