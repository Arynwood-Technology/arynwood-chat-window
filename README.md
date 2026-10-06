# Arynwood Chat Window

A chat window for your website that answers from your site's own public pages, using a model you run
yourself through [Ollama](https://ollama.com). Visitors' questions go to your server, not to an AI company.

**Status: alpha (0.2.0).** It runs, it's tested, and it hasn't served real visitors yet.

## How it works

1. **Index.** `chat-window index` reads the pages in your sitemap and splits them into passages. It skips
   anything `robots.txt` disallows or a page marks `noindex`. The passages go into one SQLite file with a
   keyword index and embeddings.
2. **Answer.** For each question, it finds the best-matching passages (keyword and meaning, fused by rank).
   The local model answers from them and links the page it used. The chat window shows those pages under
   the answer.
3. **Hand off.** When nothing on the site is close enough to the question, it says it couldn't find that and
   points to your contact page. It doesn't guess, and the model isn't called at all.

What it can't do, by design:

- **No tools.** The model has no tools, files or network access. Page text and visitor messages are framed
  as data, never instructions.
- **Your links only.** A link in an answer is clickable only when it points at your own domains. Replies are
  added to the page as text, never as HTML.
- **No tracking.** No cookies, no accounts, no tracking. The chat window loads nothing until someone opens it.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
ollama pull nomic-embed-text
ollama pull llama3.2:3b                       # an example: choose yours with `chat-window eval`

cp sites/example.toml sites/mysite.toml       # edit: name, origins, contact, sitemap, domains
export CHAT_WINDOW_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

.venv/bin/chat-window index mysite            # crawl and build data/mysite/index.sqlite
.venv/bin/chat-window ask mysite "What do you sell?"
.venv/bin/chat-window eval mysite evals/mysite.jsonl
.venv/bin/chat-window serve                   # http://127.0.0.1:8790
```

## Put it on a site

```html
<script src="https://chat.example.com/chat-window.js" data-site="mysite" defer></script>
```

| Attribute | Default | Meaning |
|---|---|---|
| `data-site` | (required) | The site's id: its file name in `sites/` |
| `data-endpoint` | the script's origin | Where the server is, if the script is hosted elsewhere |
| `data-accent` | `#2f6f5e` | Header and button colour. Pick one dark enough for white text |
| `data-position` | `right` | `left` or `right` |
| `data-label` | `Chat` | The launcher's label |

The page must be on the site's `allowed_origins`. If the server is proxied at `/chat-window/` on the site's own
domain, use `src="/chat-window/chat-window.js"`. The chat window finds its server from where the script came
from. PHP sites can use `examples/embed.php`, which also adds the request's CSP nonce.

## Deploy

[docs/deploy.md](docs/deploy.md) covers three ways to install the server:

- **`deploy/install.sh`**, for Debian or Ubuntu with systemd: one command, safe to re-run;
- **Docker Compose**, with Ollama in a container next to it;
- **by hand.**

It also has nginx and Apache snippets for serving the chat from the site's own domain, and a pre-launch
checklist. After installing, `chat-window doctor SITE` checks the whole path: settings, Ollama, models, GPU,
index and one real answer.

**Content Security Policy.** A site with a CSP needs two changes:

- add the chat server to `connect-src`;
- let the script load, with the page's nonce on the `<script>` tag or the server added to `script-src`.

The chat window needs no `unsafe-inline`: its styles are a constructed stylesheet inside its own shadow root.
If you proxy the server under the site's own domain, `'self'` covers both. See [docs/deploy.md](docs/deploy.md).

## Choosing a model

Quality depends on the site, so measure it on yours. Write a question set (`evals/arynwood.jsonl` shows the
format), then run each candidate:

```bash
chat-window eval mysite evals/mysite.jsonl --model llama3.2:3b --out results.json
```

The question set covers:

- answerable questions (the right page must be found);
- questions the site doesn't cover (it must hand off);
- off-topic requests and jailbreaks (it must decline);
- planted text, as if a page had been tampered with (it must not obey it).

Any answer that links off-site, or quotes a price that isn't on the pages it read, fails.

On Arynwood's own site, the examples we tried all passed 23 of 23: Llama 3.2 3B (Meta), Phi-4-mini
(Microsoft), Granite 3.3 8B (IBM) and Hermes 3 8B (Nous Research). Llama 3.2 3B was the fastest.

On another site, Phi-4-mini quoted two prices that weren't on the pages it was given, and Llama 3.2 3B
didn't. These are examples, not recommendations; run the question set on your own site.

## Privacy

Chats are kept for 30 days (configurable per site) for security, monitoring and improving the assistant,
then deleted. The chat window says so under its title.

Visitor addresses are never stored, only a keyed hash. "Delete this chat" in the window removes that chat's
records at once. Exports for review or training are redacted.

Details and the site owner's part: [docs/privacy.md](docs/privacy.md).

## Server settings

| Variable | Default | |
|---|---|---|
| `CHAT_WINDOW_SITES` | `sites` | Directory of site files |
| `CHAT_WINDOW_DATA` | `data` | Indexes and the chat log |
| `CHAT_WINDOW_SECRET` | (required) | Keys the hashed visitor addresses. Keep it private |
| `CHAT_WINDOW_TRUSTED_PROXIES` | `127.0.0.1,::1` | Addresses or networks whose client-address header is believed |
| `CHAT_WINDOW_CLIENT_IP_HEADER` | `X-Real-IP` | That header |
| `CHAT_WINDOW_MAX_CONCURRENT` | `1` | Answers generated at once |
| `CHAT_WINDOW_MAX_QUEUE` | `8` | Answers allowed to wait; beyond that, visitors are asked to retry |
| `CHAT_WINDOW_HOST`, `CHAT_WINDOW_PORT` | `127.0.0.1`, `8790` | Where `serve` listens |
| `CHAT_WINDOW_OLLAMA_URL` | (unset) | Overrides every site's `ollama_url`, e.g. `http://ollama:11434` in Docker |

Per-site settings (rate limits, retention, model, retrieval threshold) are in each site file; see
`sites/example.toml`.

## FAQ

**Does it send my visitors' questions to an AI company?**
No. The model runs on your own server through Ollama. Questions go from the visitor's browser to your chat
server and nowhere else.

**Can it reveal private or internal information?**
It only knows the pages your sitemap lists that search engines are also allowed to read: `robots.txt`
exclusions and `noindex` pages are skipped. Keep internal pages out of the sitemap, and use `exclude`
patterns for anything else. It has no access to your server's files, databases or other systems.

**What hardware does it need?**
A small GPU is enough. Llama 3.2 3B fits in about 3 GB of video memory with embeddings run on the CPU, so a
4 GB card works. Without a GPU it still runs, but the first word of each answer can take ten seconds or more.
`chat-window eval` reports the time to the first word, so measure it on your hardware.

## License

AGPL-3.0. See [LICENSE](LICENSE).

## Reviewed starter answers

An optional `suggested_answers` table gives a suggested question a reviewed answer,
an exact public source URL, and evidence phrases. The server verifies the phrases
against that page in the current index before returning the answer without an Ollama
call. A removed source or missing evidence causes a handoff. Other questions still
use normal retrieval and the local model. Use only facts checked against the cited
page and disclose when starter replies are reviewed FAQ answers.

```toml
suggestions = ["Do you ship abroad?"]
# Add this table after the other settings:
[suggested_answers."Do you ship abroad?"]
answer = "Yes. We ship to 30 countries."
source_url = "https://example.com/shipping"
evidence = ["ship to 30 countries"]
```

Answer text contains no URLs; the popup shows the validated source link separately.
Evidence checks detect removed wording, but do not replace human review when a page
changes meaning while retaining those phrases.
