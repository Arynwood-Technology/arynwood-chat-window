"""Collect a site's public pages: from its sitemap, within its own domains, as robots.txt allows.

Pages marked `noindex`, or excluded by robots.txt or the site's `exclude` patterns, are
skipped: the chat window only knows what the site already publishes to search engines.
"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import Site
from .textify import Page, parse_html

USER_AGENT = "ArynwoodChatWindow/0.1 (+https://github.com/Arynwood-Technology/arynwood-chat-window)"
MAX_BYTES = 3_000_000
MAX_SITEMAPS = 50


@dataclass
class CrawlReport:
    pages: list[Page] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=dict)

    def skip(self, url: str, why: str) -> None:
        self.skipped.setdefault(why, []).append(url)


def in_domains(url: str, domains) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme in ("http", "https") and any(host == d or host.endswith("." + d) for d in domains)


async def _get(client: httpx.AsyncClient, url: str, domains) -> tuple[str, str] | None:
    """GET a URL, following redirects only within the site's domains. Returns (final url, text)."""
    for _ in range(5):
        async with client.stream("GET", url) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers.get("location", ""))
                if not in_domains(url, domains):
                    return None
                continue
            if r.status_code != 200:
                return None
            body = bytearray()
            async for part in r.aiter_bytes():
                body += part
                if len(body) > MAX_BYTES:
                    return None
            return str(r.url), body.decode(r.encoding or "utf-8", errors="replace")
    return None


def _sitemap_urls(xml_text: str) -> tuple[list[str], list[str]]:
    """(page urls, nested sitemap urls)"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    return ([], locs) if root.tag.endswith("sitemapindex") else (locs, [])


async def discover(site: Site, client: httpx.AsyncClient) -> list[str]:
    domains = site.crawl.allow_domains
    urls: list[str] = list(site.crawl.urls)
    queue, seen = list(site.crawl.sitemaps), set()
    while queue and len(seen) < MAX_SITEMAPS:
        sitemap = queue.pop(0)
        if sitemap in seen or not in_domains(sitemap, domains):
            continue
        seen.add(sitemap)
        got = await _get(client, sitemap, domains)
        if not got:
            continue
        pages, nested = _sitemap_urls(got[1])
        urls += pages
        queue += nested
    out, unique = [], set()
    for url in urls:
        url = urldefrag(url.strip())[0]
        if url and url not in unique:
            unique.add(url)
            out.append(url)
    return out


async def _robots(client: httpx.AsyncClient, url: str, domains) -> RobotFileParser:
    parts = urlsplit(url)
    rp = RobotFileParser()
    got = await _get(client, f"{parts.scheme}://{parts.netloc}/robots.txt", domains)
    rp.parse(got[1].splitlines() if got else [])
    return rp


async def crawl(site: Site, *, log=print, transport: httpx.AsyncBaseTransport | None = None) -> CrawlReport:
    report = CrawlReport()
    domains = site.crawl.allow_domains
    excludes = [re.compile(p) for p in site.crawl.exclude]
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=False,
                                 transport=transport) as client:
        urls = await discover(site, client)
        robots: dict[str, RobotFileParser] = {}
        canonicals: set[str] = set()
        for url in urls:
            if len(report.pages) >= site.crawl.max_pages:
                report.skip(url, "max_pages reached")
                continue
            if not in_domains(url, domains):
                report.skip(url, "outside allowed domains")
                continue
            path = urlsplit(url).path or "/"
            if any(p.search(path) for p in excludes):
                report.skip(url, "excluded by config")
                continue
            netloc = urlsplit(url).netloc
            if netloc not in robots:
                robots[netloc] = await _robots(client, url, domains)
            if not robots[netloc].can_fetch(USER_AGENT, url):
                report.skip(url, "disallowed by robots.txt")
                continue
            try:
                got = await _get(client, url, domains)
            except httpx.HTTPError:
                got = None
            if not got:
                report.skip(url, "fetch failed or redirected off-site")
                continue
            final, html = got
            page = parse_html(final, html)
            if page.noindex:
                report.skip(url, "noindex")
                continue
            if site.crawl.lang and page.lang and not page.lang.startswith(site.crawl.lang):
                report.skip(url, f"language {page.lang}")
                continue
            canonical = urljoin(final, page.canonical) if page.canonical else final
            if canonical in canonicals:
                report.skip(url, "duplicate of a canonical page")
                continue
            canonicals.add(canonical)
            if in_domains(canonical, domains):
                page.url = urldefrag(canonical)[0]
            report.pages.append(page)
            log(f"  {len(report.pages):4d}  {page.url}  ({len(page.sections)} sections)")
            await asyncio.sleep(site.crawl.delay_seconds)
    return report
