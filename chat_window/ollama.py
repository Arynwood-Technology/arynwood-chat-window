"""The two Ollama calls this needs: embeddings and a streamed chat reply."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

# nomic-embed-text is trained with these task prefixes; other models ignore them harmlessly.
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class ModelError(RuntimeError):
    pass


async def embed(texts: list[str], url: str, model: str, *, query: bool = False, gpu: bool = False,
                timeout: float = 120.0) -> list[list[float]]:
    prefix = QUERY_PREFIX if query else DOC_PREFIX
    payload = {"model": model, "input": [prefix + t for t in texts], "truncate": True}
    if not gpu:
        payload["options"] = {"num_gpu": 0}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{url}/api/embed", json=payload)
            r.raise_for_status()
            vectors = r.json().get("embeddings") or []
    except httpx.HTTPError as exc:
        raise ModelError(f"embedding model {model!r} at {url} failed: {exc}") from exc
    if len(vectors) != len(texts):
        raise ModelError(f"embedding model {model!r} returned {len(vectors)} vectors for {len(texts)} texts")
    return vectors


async def chat_stream(messages: list[dict], url: str, model: str, *, num_ctx: int, max_tokens: int,
                      temperature: float, keep_alive: str, timeout: float = 300.0) -> AsyncIterator[str]:
    payload = {"model": model, "messages": messages, "stream": True, "keep_alive": keep_alive,
               "options": {"num_ctx": num_ctx, "num_predict": max_tokens, "temperature": temperature}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            async with client.stream("POST", f"{url}/api/chat", json=payload) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")[:300]
                    raise ModelError(f"chat model {model!r} returned {r.status_code}: {body}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise ModelError(str(event["error"]))
                    text = (event.get("message") or {}).get("content") or ""
                    if text:
                        yield text
                    if event.get("done"):
                        return
    except httpx.HTTPError as exc:
        raise ModelError(f"chat model {model!r} at {url} failed: {exc}") from exc


async def available(url: str, models: list[str], timeout: float = 5.0) -> dict[str, bool]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{url}/api/tags")
            r.raise_for_status()
            names = {m.get("name", "") for m in r.json().get("models", [])}
    except httpx.HTTPError:
        return {m: False for m in models}
    full = names | {n.removesuffix(":latest") for n in names}
    return {m: m in full or f"{m}:latest" in names for m in models}
