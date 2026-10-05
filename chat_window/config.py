"""Site and server configuration.

Each site is one TOML file, `<sites dir>/<id>.toml`. Server-wide settings come from the
environment so one process can serve many sites.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import os
import re
try:
    import tomllib
except ModuleNotFoundError:          # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Crawl:
    sitemaps: tuple[str, ...] = ()
    urls: tuple[str, ...] = ()
    allow_domains: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()       # regular expressions matched against the URL path
    lang: str = ""                      # skip pages whose <html lang> doesn't start with this
    max_pages: int = 500
    delay_seconds: float = 0.5


@dataclass(frozen=True)
class Model:
    ollama_url: str = "http://127.0.0.1:11434"
    chat: str = "llama3.2:3b"
    embed: str = "nomic-embed-text"
    embed_on_gpu: bool = False          # CPU embeddings leave a small card's memory to the chat model
    num_ctx: int = 4096
    max_answer_tokens: int = 350
    temperature: float = 0.2
    keep_alive: str = "30m"


@dataclass(frozen=True)
class Retrieval:
    top_k: int = 4
    min_score: float = 0.6              # cosine similarity a passage needs for the site to "cover" a question
    max_chars_per_excerpt: int = 1100


@dataclass(frozen=True)
class Limits:
    per_minute: int = 6
    per_day: int = 60
    max_message_chars: int = 600
    max_turns: int = 6


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    description: str
    allowed_origins: tuple[str, ...]
    contact: str
    greeting: str = ""
    notice: str = ""
    privacy_url: str = ""
    suggestions: tuple[str, ...] = ()
    retention_days: int = 30
    crawl: Crawl = field(default_factory=Crawl)
    model: Model = field(default_factory=Model)
    retrieval: Retrieval = field(default_factory=Retrieval)
    limits: Limits = field(default_factory=Limits)

    @property
    def link_domains(self) -> tuple[str, ...]:
        """Domains an answer may link to: the crawled site's own."""
        return self.crawl.allow_domains

    def public_notice(self) -> str:
        return self.notice or (
            f"Answers come from {self.name}'s website and can be wrong. Chats are kept for "
            f"{self.retention_days} days for security, monitoring and to train and improve this "
            "assistant, then deleted.")

    def public(self) -> dict:
        """What the chat window may show. Nothing here is secret."""
        return {
            "id": self.id, "name": self.name, "greeting": self.greeting or f"Hi! Ask me about {self.name}.",
            "notice": self.public_notice(), "privacy_url": self.privacy_url,
            "suggestions": list(self.suggestions), "retention_days": self.retention_days,
            "link_domains": list(self.link_domains), "max_message_chars": self.limits.max_message_chars,
        }


def _section(data: dict, name: str, cls):
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a table")
    known = {f for f in cls.__dataclass_fields__}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"[{name}] has unknown keys: {', '.join(sorted(unknown))}")
    values = {k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()}
    return cls(**values)


def _origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.netloc or parts.path not in ("", "/") or parts.query:
        raise ConfigError(f"allowed_origins entry {value!r} must be a bare origin like https://example.com")
    return f"{parts.scheme}://{parts.netloc}".lower()


def parse_site(site_id: str, data: dict) -> Site:
    if not SITE_ID.match(site_id):
        raise ConfigError(f"site id {site_id!r} must be lowercase letters, digits and dashes")
    for key in ("name", "description", "allowed_origins", "contact"):
        if not data.get(key):
            raise ConfigError(f"{site_id}: missing required key {key!r}")
    top = {"name", "description", "allowed_origins", "contact", "greeting", "notice", "privacy_url",
           "suggestions", "retention_days", "crawl", "model", "retrieval", "limits"}
    unknown = set(data) - top
    if unknown:
        raise ConfigError(f"{site_id}: unknown keys: {', '.join(sorted(unknown))}")
    crawl = _section(data, "crawl", Crawl)
    if not crawl.allow_domains:
        raise ConfigError(f"{site_id}: [crawl] allow_domains is required")
    for pattern in crawl.exclude:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{site_id}: bad exclude pattern {pattern!r}: {exc}") from exc
    retention = int(data.get("retention_days", 30))
    if not 1 <= retention <= 365:
        raise ConfigError(f"{site_id}: retention_days must be between 1 and 365")
    return Site(
        id=site_id, name=str(data["name"]), description=str(data["description"]),
        allowed_origins=tuple(_origin(o) for o in data["allowed_origins"]),
        contact=str(data["contact"]), greeting=str(data.get("greeting", "")),
        notice=str(data.get("notice", "")), privacy_url=str(data.get("privacy_url", "")),
        suggestions=tuple(str(s) for s in data.get("suggestions", ()))[:4], retention_days=retention,
        crawl=crawl, model=_section(data, "model", Model),
        retrieval=_section(data, "retrieval", Retrieval), limits=_section(data, "limits", Limits),
    )


def load_site(path: Path) -> Site:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return parse_site(path.stem, data)


def parse_networks(value: str) -> tuple:
    """'127.0.0.1, 10.0.0.0/8, ::1' -> networks. A bad entry is a configuration error, not ignored."""
    networks = []
    for entry in (e.strip() for e in value.split(",")):
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise ConfigError(f"CHAT_WINDOW_TRUSTED_PROXIES: {entry!r} isn't an address or network") from exc
    return tuple(networks)


@dataclass(frozen=True)
class Settings:
    sites_dir: Path
    data_dir: Path
    secret: str                       # keys the hashed visitor addresses in the log
    trusted_proxies: tuple            # networks whose client-address header is believed
    client_ip_header: str
    max_concurrent: int
    max_queue: int
    host: str = "127.0.0.1"
    port: int = 8790
    ollama_url: str = ""              # overrides every site's [model] ollama_url (e.g. in Docker)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            sites_dir=Path(os.environ.get("CHAT_WINDOW_SITES", "sites")),
            data_dir=Path(os.environ.get("CHAT_WINDOW_DATA", "data")),
            secret=os.environ.get("CHAT_WINDOW_SECRET", ""),
            trusted_proxies=parse_networks(os.environ.get("CHAT_WINDOW_TRUSTED_PROXIES", "127.0.0.1,::1")),
            client_ip_header=os.environ.get("CHAT_WINDOW_CLIENT_IP_HEADER", "X-Real-IP"),
            max_concurrent=int(os.environ.get("CHAT_WINDOW_MAX_CONCURRENT", "1")),
            max_queue=int(os.environ.get("CHAT_WINDOW_MAX_QUEUE", "8")),
            host=os.environ.get("CHAT_WINDOW_HOST", "127.0.0.1"),
            port=int(os.environ.get("CHAT_WINDOW_PORT", "8790")),
            ollama_url=os.environ.get("CHAT_WINDOW_OLLAMA_URL", "").rstrip("/"),
        )

    def trusts(self, address: str) -> bool:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        return any(ip in network for network in self.trusted_proxies)

    def load_sites(self) -> dict[str, Site]:
        sites = {}
        for path in sorted(self.sites_dir.glob("*.toml")):
            if path.stem == "example":
                continue
            site = load_site(path)
            if self.ollama_url:
                site = dataclasses.replace(site, model=dataclasses.replace(site.model, ollama_url=self.ollama_url))
            sites[site.id] = site
        return sites

    def site_dir(self, site_id: str) -> Path:
        return self.data_dir / site_id
