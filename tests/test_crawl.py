import asyncio

import httpx

from chat_window.crawl import _sitemap_urls, crawl, in_domains

from .conftest import make_site

SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://demo.example/pages.xml</loc></sitemap></sitemapindex>"""
PAGES = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://demo.example/</loc></url><url><loc>https://demo.example/plans</loc></url>
<url><loc>https://demo.example/private/notes</loc></url><url><loc>https://demo.example/draft</loc></url>
<url><loc>https://demo.example/es/plans</loc></url><url><loc>https://demo.example/cart</loc></url>
<url><loc>https://demo.example/out</loc></url><url><loc>https://other.example/page</loc></url>
<url><loc>https://demo.example/plans?ref=x</loc></url></urlset>"""


def page(body, extra="", lang="en"):
    return f'<html lang="{lang}"><head><title>T</title>{extra}</head><body><h1>T</h1><p>{body}</p></body></html>'


ROUTES = {
    "/sitemap.xml": (200, SITEMAP_INDEX), "/pages.xml": (200, PAGES),
    "/robots.txt": (200, "User-agent: *\nDisallow: /private/\n"),
    "/": (200, page("Home text")),
    "/plans": (200, page("Plan text", '<link rel="canonical" href="https://demo.example/plans">')),
    "/private/notes": (200, page("Internal notes")),
    "/draft": (200, page("Draft", '<meta name="robots" content="noindex">')),
    "/es/plans": (200, page("Planes", lang="es")),
    "/cart": (200, page("Cart")),
}


def handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["user-agent"].startswith("ArynwoodChatWindow/")
    path = request.url.path
    if path == "/out":
        return httpx.Response(302, headers={"location": "https://evil.example/landing"})
    if request.url.host != "demo.example":
        raise AssertionError(f"crawler left the site: {request.url}")
    status, body = ROUTES.get(path, (404, "nope"))
    return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


def test_crawl_reads_only_public_indexable_pages():
    site = make_site(crawl={"exclude": ["^/cart"], "lang": "en", "delay_seconds": 0})
    report = asyncio.run(crawl(site, log=lambda *_: None, transport=httpx.MockTransport(handler)))
    assert [p.url for p in report.pages] == ["https://demo.example/", "https://demo.example/plans"]
    skipped = {why: urls for why, urls in report.skipped.items()}
    assert skipped["disallowed by robots.txt"] == ["https://demo.example/private/notes"]
    assert skipped["noindex"] == ["https://demo.example/draft"]
    assert skipped["language es"] == ["https://demo.example/es/plans"]
    assert skipped["excluded by config"] == ["https://demo.example/cart"]
    assert skipped["fetch failed or redirected off-site"] == ["https://demo.example/out"]
    assert skipped["outside allowed domains"] == ["https://other.example/page"]
    assert skipped["duplicate of a canonical page"] == ["https://demo.example/plans?ref=x"]


def test_sitemap_parsing_and_domains():
    assert _sitemap_urls(SITEMAP_INDEX) == ([], ["https://demo.example/pages.xml"])
    assert len(_sitemap_urls(PAGES)[0]) == 9
    assert _sitemap_urls("not xml") == ([], [])
    assert in_domains("https://www.demo.example/x", ["demo.example"])
    assert not in_domains("https://demo.example.evil.net/", ["demo.example"])
    assert not in_domains("file:///etc/passwd", ["demo.example"])
