"""chat-window doctor SITE: check a deployment from settings to a real answer.

Exit status 0 means every check passed; 1 means at least one failed. Warnings don't fail.
"""
from __future__ import annotations

import time

import httpx

from . import answer, ollama
from .config import Settings, Site
from .index import Index


class Report:
    def __init__(self) -> None:
        self.failed = False

    def ok(self, text: str) -> None:
        print(f"  ok    {text}")

    def warn(self, text: str) -> None:
        print(f"  warn  {text}")

    def fail(self, text: str) -> None:
        self.failed = True
        print(f"  FAIL  {text}")


async def run(settings: Settings, site: Site, question: str | None = None) -> int:
    r = Report()
    print(f"Checking {site.name} ({site.id})")
    model = site.model

    if settings.secret and len(settings.secret) >= 32:
        r.ok("CHAT_WINDOW_SECRET is set")
    elif settings.secret:
        r.warn("CHAT_WINDOW_SECRET is short; use 32 or more random characters")
    else:
        r.fail("CHAT_WINDOW_SECRET isn't set; the server won't start without it")
    r.ok(f"origins allowed to embed the chat: {', '.join(site.allowed_origins)}")
    if not site.privacy_url:
        r.warn("no privacy_url: the chat's notice won't link a privacy policy")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            version = (await client.get(f"{model.ollama_url}/api/version")).json().get("version", "?")
        r.ok(f"Ollama {version} at {model.ollama_url}")
    except (httpx.HTTPError, ValueError) as exc:
        r.fail(f"Ollama isn't reachable at {model.ollama_url}: {exc}")
        return 1
    present = await ollama.available(model.ollama_url, [model.chat, model.embed])
    for name, here in present.items():
        if here:
            r.ok(f"model {name} is pulled")
        else:
            r.fail(f"model {name} is missing: ollama pull {name}")

    path = settings.site_dir(site.id) / "index.sqlite"
    if not path.exists():
        r.fail(f"no index at {path}: chat-window index {site.id}")
        return 1
    index = Index(path)
    age_h = (time.time() - int(index.meta.get("built_at", 0))) / 3600
    pages, chunks = index.meta.get("page_count", "?"), index.meta.get("chunk_count", "?")
    (r.ok if age_h < 48 else r.warn)(f"index: {pages} pages, {chunks} passages, built {age_h:.0f} h ago")
    if index.meta.get("embed_model") != model.embed:
        r.fail(f"index was built with {index.meta.get('embed_model')}, site uses {model.embed}: rebuild it")

    if not all(present.values()):
        return 1
    question = question or (site.suggestions[0] if site.suggestions else f"What does {site.name} offer?")
    started = time.monotonic()
    try:
        retrieved = await answer.retrieve(site, index, question, [])
        first, pieces = None, []
        async for piece in answer.stream_answer(site, question, retrieved, []):
            first = first or time.monotonic() - started
            pieces.append(piece)
    except ollama.ModelError as exc:
        r.fail(f"answering failed: {exc}")
        return 1
    total = time.monotonic() - started
    reply = " ".join("".join(pieces).split())
    if retrieved.covered and reply:
        r.ok(f"answered {question!r}: first word {first:.1f} s, whole answer {total:.1f} s")
        print(f"        {reply[:240]}")
    else:
        r.warn(f"{question!r} was judged not covered (top similarity "
               f"{max((h.similarity for h in retrieved.hits), default=0):.2f}); try --question")
    if first and first > 8:
        r.warn("the first word took over 8 s: visitors will wait; check the GPU line below")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            loaded = (await client.get(f"{model.ollama_url}/api/ps")).json().get("models", [])
        wanted = {model.chat.removesuffix(":latest"): True, model.embed.removesuffix(":latest"): model.embed_on_gpu}
        for m in loaded:
            name = m.get("name", "").removesuffix(":latest")
            if name not in wanted:
                continue
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            share = round(100 * vram / size) if size else 0
            text = f"{name} is {share}% on the GPU ({vram / 2**30:.1f} of {size / 2**30:.1f} GB)"
            if not wanted[name]:
                r.ok(text + " (embed_on_gpu = false)")
            else:
                (r.ok if share >= 99 else r.warn)(text + ("" if share >= 99 else ": the rest runs on the CPU, slower"))
    except (httpx.HTTPError, ValueError):
        r.warn("couldn't read what Ollama has loaded (/api/ps)")

    print("All checks passed." if not r.failed else "Some checks failed.")
    return 1 if r.failed else 0
