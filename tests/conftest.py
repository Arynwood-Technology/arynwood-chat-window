import pytest

from chat_window.config import parse_site


def make_site(site_id="demo", **overrides):
    data = {
        "name": "Demo Co.", "description": "Demo Co. sells widgets.",
        "allowed_origins": ["https://demo.example"], "contact": "https://demo.example/contact",
        "crawl": {"sitemaps": ["https://demo.example/sitemap.xml"], "allow_domains": ["demo.example"]},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return parse_site(site_id, data)


@pytest.fixture
def site():
    return make_site()
