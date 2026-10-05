import re
import shutil
import subprocess
from pathlib import Path

import pytest

WIDGET = Path(__file__).resolve().parent.parent / "chat_window" / "static" / "chat-window.js"
SOURCE = WIDGET.read_text()


def test_widget_never_builds_html_from_strings():
    # Every reply is model output: it must reach the page as text nodes and checked links only.
    for risky in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert risky not in SOURCE, risky


def test_widget_sends_no_cookies_or_referrer():
    assert "credentials: 'omit'" in SOURCE and "referrerPolicy: 'no-referrer'" in SOURCE


def test_widget_links_only_to_the_site_and_opens_safely():
    assert "allowedUrl(" in SOURCE
    for match in re.finditer(r"el\('a', \{([^}]*)\}", SOURCE):
        assert "noopener" in match.group(1)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_widget_parses():
    subprocess.run(["node", "--check", str(WIDGET)], check=True)
