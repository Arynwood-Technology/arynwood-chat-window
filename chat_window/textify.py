"""Turn a web page into titled sections of plain text, and sections into chunks.

Standard library only. The page's <main> is used when it has one; otherwise the <body>
without its header, navigation, footer, forms and scripts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "template", "svg", "form", "button", "select", "iframe", "canvas"}
CHROME = {"header", "nav", "footer"}          # dropped unless they're inside <main>
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "summary": 5, "dt": 5}  # an FAQ question is a heading
BLOCKS = {"p", "div", "section", "article", "li", "tr", "br", "dd", "blockquote", "pre",
          "table", "ul", "ol", "details", "figcaption", "td", "th"}
VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "area", "base", "col", "embed",
        "param", "track"}


@dataclass
class Section:
    heading: str
    anchor: str
    text: str


@dataclass
class Page:
    url: str
    title: str = ""
    lang: str = ""
    description: str = ""
    canonical: str = ""
    noindex: bool = False
    sections: list[Section] = field(default_factory=list)


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.skip_depth = 0
        self.in_title = False
        self.title = ""
        self.lang = ""
        self.description = ""
        self.canonical = ""
        self.noindex = False
        self.has_main = False
        self.main_depth = 0
        # Two streams: everything in <main>, and the body without chrome. One is used.
        self.main_parts: list[tuple] = []
        self.body_parts: list[tuple] = []
        self.chrome_depth = 0
        self.heading: tuple[int, str, list[str]] | None = None

    def _emit(self, item: tuple) -> None:
        if self.main_depth:
            self.main_parts.append(item)
        if not self.chrome_depth:
            self.body_parts.append(item)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = (a.get("lang") or "").lower()
        if tag == "meta":
            name = (a.get("name") or "").lower()
            if name == "description":
                self.description = a.get("content") or ""
            if name == "robots" and "noindex" in (a.get("content") or "").lower():
                self.noindex = True
        if tag == "link" and "canonical" in (a.get("rel") or "").lower():
            self.canonical = a.get("href") or ""
        if tag in VOID:
            if tag == "br":
                self._emit(("break",))
            return
        self.stack.append(tag)
        hidden = "hidden" in a or a.get("aria-hidden") == "true"
        if self.skip_depth or tag in SKIP or hidden:
            self.skip_depth += 1
            return
        if tag == "title":
            self.in_title = True
        if tag == "main":
            self.has_main = True
            self.main_depth += 1
        elif tag in CHROME or a.get("role") in ("navigation", "banner", "contentinfo"):
            self.chrome_depth += 1
            self.stack[-1] = tag + "\0chrome"
        if tag in HEADINGS:
            self.heading = (HEADINGS[tag], a.get("id") or "", [])
        elif tag in BLOCKS:
            self._emit(("break",))
        if tag in ("section", "article", "div") and a.get("id") and not self.heading:
            self._emit(("anchor", a["id"]))

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        # Close up to the matching tag; tolerate sloppy markup.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].split("\0")[0] == tag:
                break
        else:
            return
        while len(self.stack) > i:
            self._close(self.stack.pop())

    def _close(self, entry: str) -> None:
        tag, _, marker = entry.partition("\0")
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        if tag == "main":
            self.main_depth -= 1
        if marker == "chrome":
            self.chrome_depth -= 1
        if tag in HEADINGS and self.heading:
            level, anchor, words = self.heading
            self.heading = None
            text = " ".join(" ".join(words).split())
            if text:
                self._emit(("heading", level, anchor, text))
        elif tag in BLOCKS:
            self._emit(("break",))

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_title:
            self.title += data
            return
        if self.heading:
            self.heading[2].append(data)
            return
        if data.strip():
            self._emit(("text", data))


def _sections(parts: list[tuple]) -> list[Section]:
    sections: list[Section] = []
    path: dict[int, str] = {}
    heading, anchor, lines, current = "", "", [], []

    def flush_line():
        line = " ".join("".join(current).split())
        if line:
            lines.append(line)
        current.clear()

    def flush_section():
        flush_line()
        text = "\n".join(lines).strip()
        if text:
            sections.append(Section(heading, anchor, text))
        lines.clear()

    for item in parts:
        kind = item[0]
        if kind == "text":
            current.append(item[1])
        elif kind == "break":
            flush_line()
        elif kind == "anchor":
            if not lines and not current:
                anchor = item[1]
        elif kind == "heading":
            flush_section()
            level, new_anchor, text = item[1], item[2], item[3]
            path = {lv: t for lv, t in path.items() if lv < level}
            path[level] = text
            heading = " › ".join(path[lv] for lv in sorted(path) if lv > 1) or text
            anchor = new_anchor
    flush_section()
    return sections


def parse_html(url: str, html: str) -> Page:
    reader = _Reader()
    reader.feed(html)
    reader.close()
    parts = reader.main_parts if reader.has_main and reader.main_parts else reader.body_parts
    return Page(url=url, title=" ".join(reader.title.split()), lang=reader.lang,
                description=" ".join(reader.description.split()), canonical=reader.canonical,
                noindex=reader.noindex, sections=_sections(parts))


@dataclass
class Chunk:
    url: str
    title: str
    heading: str
    text: str


def chunk_page(page: Page, max_chars: int = 900, overlap: int = 150) -> list[Chunk]:
    """Split each section into chunks of whole lines (or sentences when a line is long)."""
    chunks: list[Chunk] = []
    for section in page.sections:
        link = f"{page.url}#{section.anchor}" if section.anchor else page.url
        pieces: list[str] = []
        for line in section.text.split("\n"):
            if len(line) <= max_chars:
                pieces.append(line)
            else:
                pieces.extend(s for s in re.split(r"(?<=[.!?])\s+", line) if s)
        buf = ""
        for piece in pieces:
            piece = piece[:max_chars]
            if buf and len(buf) + 1 + len(piece) > max_chars:
                chunks.append(Chunk(link, page.title, section.heading, buf))
                tail = buf[-overlap:]
                buf = (tail[tail.find(" ") + 1:] + "\n" + piece) if overlap else piece
            else:
                buf = f"{buf}\n{piece}" if buf else piece
        if buf.strip():
            chunks.append(Chunk(link, page.title, section.heading, buf))
    if not chunks and page.description:
        chunks.append(Chunk(page.url, page.title, "", page.description))
    return chunks
