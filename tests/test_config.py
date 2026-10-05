from pathlib import Path

import pytest

from chat_window.config import ConfigError, load_site, parse_site

from .conftest import make_site

ROOT = Path(__file__).resolve().parent.parent


def test_bundled_site_files_load():
    for path in (ROOT / "sites").glob("*.toml"):
        site = load_site(path)
        assert site.allowed_origins and site.crawl.allow_domains


def test_defaults_and_public_view(site):
    assert site.retention_days == 30
    view = site.public()
    assert view["link_domains"] == ["demo.example"]
    assert "30 days" in view["notice"]
    assert "contact" not in view and "description" not in view   # the prompt's material stays server-side


@pytest.mark.parametrize("bad_id", ["Demo", "-x", "a" * 41, "a/b", ""])
def test_site_ids_are_restricted(bad_id):
    with pytest.raises(ConfigError):
        make_site(bad_id)


@pytest.mark.parametrize("origin", ["demo.example", "https://demo.example/path", "ftp://demo.example",
                                    "https://demo.example/?q=1"])
def test_origins_must_be_bare(origin):
    with pytest.raises(ConfigError):
        make_site(allowed_origins=[origin])


def test_origins_are_normalized():
    assert make_site(allowed_origins=["HTTPS://Demo.Example/"]).allowed_origins == ("https://demo.example",)


def test_unknown_keys_and_missing_keys_are_errors():
    with pytest.raises(ConfigError):
        make_site(colour="blue")
    with pytest.raises(ConfigError):
        make_site(model={"temprature": 0.1})
    with pytest.raises(ConfigError):
        parse_site("demo", {"name": "x", "description": "y", "allowed_origins": ["https://a.example"]})


def test_crawl_needs_domains_and_valid_patterns():
    with pytest.raises(ConfigError):
        make_site(crawl={"allow_domains": []})
    with pytest.raises(ConfigError):
        make_site(crawl={"exclude": ["("]})


def test_retention_is_bounded():
    with pytest.raises(ConfigError):
        make_site(retention_days=0)
    with pytest.raises(ConfigError):
        make_site(retention_days=400)


def test_environment_settings(monkeypatch, tmp_path):
    from chat_window.config import Settings
    (tmp_path / "demo.toml").write_text(
        'name="D"\ndescription="d"\nallowed_origins=["https://d.example"]\ncontact="c"\n'
        '[crawl]\nallow_domains=["d.example"]\n')
    (tmp_path / "example.toml").write_text("ignored = true\n")
    monkeypatch.setenv("CHAT_WINDOW_SITES", str(tmp_path))
    monkeypatch.setenv("CHAT_WINDOW_OLLAMA_URL", "http://ollama:11434/")
    monkeypatch.setenv("CHAT_WINDOW_HOST", "0.0.0.0")
    monkeypatch.setenv("CHAT_WINDOW_TRUSTED_PROXIES", "172.16.0.0/12")
    settings = Settings.from_env()
    sites = settings.load_sites()
    assert list(sites) == ["demo"] and sites["demo"].model.ollama_url == "http://ollama:11434"
    assert settings.host == "0.0.0.0" and settings.trusts("172.18.0.1") and not settings.trusts("10.0.0.1")
