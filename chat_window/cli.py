"""chat-window: index a site, try it, check it, run it.

    chat-window index SITE            crawl the site's public pages and build its index
    chat-window search SITE "words"   show what retrieval finds
    chat-window ask SITE "question"   answer in the terminal
    chat-window eval SITE [FILE]      run the site's question set (default evals/SITE.jsonl)
    chat-window stats SITE            what the log says about the last 7 days
    chat-window export SITE           redacted chats, as JSONL, for review or training
    chat-window purge                 delete log rows past each site's retention
    chat-window serve                 run the web server
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from pathlib import Path

from . import answer, ollama
from .config import Settings, Site
from .crawl import crawl
from .index import Index, build
from .textify import chunk_page


def _site(settings: Settings, site_id: str) -> Site:
    sites = settings.load_sites()
    if site_id not in sites:
        known = ", ".join(sites) or "none"
        sys.exit(f"No site {site_id!r} in {settings.sites_dir} (found: {known}).")
    return sites[site_id]


def _index(settings: Settings, site: Site) -> Index:
    path = settings.site_dir(site.id) / "index.sqlite"
    if not path.exists():
        sys.exit(f"No index for {site.id}. Run: chat-window index {site.id}")
    return Index(path)


async def cmd_index(settings: Settings, site: Site) -> None:
    print(f"Crawling {site.name} …")
    report = await crawl(site)
    chunks = [c for page in report.pages for c in chunk_page(page)]
    if not chunks:
        sys.exit("No text found on any page; nothing to index.")
    print(f"{len(report.pages)} pages, {len(chunks)} chunks. Embedding with {site.model.embed} …")
    vectors: list[list[float]] = []
    started = time.monotonic()
    for i in range(0, len(chunks), 32):
        batch = chunks[i:i + 32]
        text = [f"{c.title}\n{c.heading}\n{c.text}" for c in batch]
        vectors += await ollama.embed(text, site.model.ollama_url, site.model.embed, gpu=site.model.embed_on_gpu)
    out = settings.site_dir(site.id)
    build(out / "index.sqlite", chunks, vectors,
          {"site": site.id, "embed_model": site.model.embed, "page_count": len(report.pages)})
    (out / "crawl-report.json").write_text(json.dumps(
        {"pages": [p.url for p in report.pages], "skipped": report.skipped}, indent=1))
    print(f"Built {out / 'index.sqlite'} in {time.monotonic() - started:.0f}s.")
    for why, urls in report.skipped.items():
        print(f"  skipped {len(urls):4d}: {why}")


async def cmd_search(settings: Settings, site: Site, words: str) -> None:
    index = _index(settings, site)
    vector = (await ollama.embed([words], site.model.ollama_url, site.model.embed, query=True,
                                 gpu=site.model.embed_on_gpu))[0]
    for hit in index.search(words, vector, top_k=site.retrieval.top_k):
        print(f"{hit.similarity:.3f}  {hit.url}\n       {hit.heading or hit.title}\n       "
              f"{hit.text[:160].replace(chr(10), ' ')}")


async def cmd_ask(settings: Settings, site: Site, question: str) -> None:
    index = _index(settings, site)
    retrieved = await answer.retrieve(site, index, question, [])
    print(f"covered: {retrieved.covered}; sources: {[s['url'] for s in retrieved.sources()]}\n")
    async for piece in answer.stream_answer(site, question, retrieved, []):
        print(piece, end="", flush=True)
    print()


async def cmd_eval(settings: Settings, site: Site, path: Path, model: str | None, out: Path | None) -> None:
    from .evals import load_cases, run_case, summarize
    if model:
        site = dataclasses.replace(site, model=dataclasses.replace(site.model, chat=model))
    index = _index(settings, site)
    results = []
    for case in load_cases(path):
        r = await run_case(site, index, case)
        results.append(r)
        mark = "ok  " if r.passed else "FAIL"
        print(f"{mark} {r.kind:9s} sim {r.top_similarity:.3f} {r.first_token_s:5.1f}s  {r.q[:64]}" + (f"\n       {r.why}" if r.why else ""))
    summary = {"site": site.id, "model": site.model.chat, **summarize(results)}
    print(json.dumps(summary, indent=1))
    if out:
        out.write_text(json.dumps({"summary": summary, "results": [dataclasses.asdict(r) for r in results]},
                                  indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="chat-window", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("index", "stats", "export"):
        p = sub.add_parser(name)
        p.add_argument("site")
        if name == "stats":
            p.add_argument("--days", type=int, default=7)
        if name == "export":
            p.add_argument("--days", type=int)
    for name in ("search", "ask"):
        p = sub.add_parser(name)
        p.add_argument("site")
        p.add_argument("text")
    p = sub.add_parser("eval")
    p.add_argument("site")
    p.add_argument("file", nargs="?")
    p.add_argument("--model", help="try another chat model without editing the site file")
    p.add_argument("--out", type=Path, help="write every result as JSON")
    sub.add_parser("purge")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.cmd == "serve":
        import uvicorn
        from .server import create_app
        uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=False,
                    server_header=False)
        return
    if args.cmd in ("purge", "stats", "export"):
        from .logstore import ChatLog
        log = ChatLog(settings.data_dir / "chats.sqlite", settings.secret)
        if args.cmd == "purge":
            sites = settings.load_sites()
            print(f"Deleted {log.purge({s.id: s.retention_days for s in sites.values()})} rows.")
        elif args.cmd == "stats":
            print(json.dumps(log.stats(_site(settings, args.site).id, args.days), indent=1, ensure_ascii=False))
        else:
            for row in log.export(_site(settings, args.site).id, args.days):
                print(json.dumps(row, ensure_ascii=False))
        return
    site = _site(settings, args.site)
    if args.cmd == "index":
        asyncio.run(cmd_index(settings, site))
    elif args.cmd == "search":
        asyncio.run(cmd_search(settings, site, args.text))
    elif args.cmd == "ask":
        asyncio.run(cmd_ask(settings, site, args.text))
    elif args.cmd == "eval":
        path = Path(args.file) if args.file else Path("evals") / f"{site.id}.jsonl"
        asyncio.run(cmd_eval(settings, site, path, args.model, args.out))


if __name__ == "__main__":
    main()
