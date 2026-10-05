# Deploying

The chat runs as two pieces:

- **The chat server.** It runs on a machine you control, next to Ollama, which runs the models.
- **The chat window.** The website loads it with one `<script>` tag.

One server can serve many sites. Each site has its own file in the sites directory and its own index.

```
visitor's browser ──► your website (adds the <script> tag)
        │
        └──► /chat-window/ on the same domain (proxied) ──► chat server :8790 ──► Ollama :11434
```

## 1. Install the chat server

Pick one of three ways.

### A. The installer (Debian or Ubuntu with systemd)

```bash
git clone https://github.com/Arynwood-Technology/arynwood-chat-window
cd arynwood-chat-window
sudo deploy/install.sh --site /path/to/mysite.toml --evals /path/to/mysite.jsonl
```

It does everything:

- creates a `chatwindow` system account;
- installs the code in `/opt/arynwood-chat-window` and writes `/etc/arynwood-chat-window/env` with a new
  secret;
- pulls the site's models into Ollama;
- builds the site's index, and starts the service and a nightly re-index timer;
- runs `chat-window doctor` and the question set.

Running it again upgrades the code and keeps the secret, the log and the indexes.

For day-to-day commands, `sudo chat-window-admin <command>` runs as the service account with its
settings: `doctor`, `stats`, `index`, `export`, `purge`.

Options:

- `--host` and `--port` set where it listens (default `127.0.0.1:8790`).
- `--trusted-proxies` names the reverse proxies whose client-address header is believed. Use an address or
  network such as `10.0.0.5` or `10.0.0.0/24`.

Ollama must already be installed and running on `127.0.0.1`. See [ollama.com/download/linux](https://ollama.com/download/linux).

### B. Docker Compose (Ollama and the chat server in containers)

```bash
cd deploy
cp chat-window.env.example chat-window.env     # set CHAT_WINDOW_SECRET
mkdir -p sites && cp /path/to/mysite.toml sites/
docker compose up -d --build
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull nomic-embed-text
docker compose run --rm chat-window index mysite
docker compose run --rm chat-window doctor mysite
```

- **GPU.** The GPU needs the NVIDIA Container Toolkit. Without a GPU, delete the `deploy:` block from
  `docker-compose.yml`.
- **Nightly re-index.** Add a cron line on the host:
  `30 4 * * * cd /path/to/deploy && docker compose run --rm chat-window index mysite`.

### C. By hand

```bash
python3 -m venv venv
venv/bin/pip install .
CHAT_WINDOW_SECRET=... venv/bin/chat-window serve
```

The units in `deploy/` show the systemd setup the installer uses.

## 2. Put it behind the website

**Same domain (recommended).** Proxy `https://example.com/chat-window/` to the chat server. A page with a
Content Security Policy then needs no new host: `connect-src 'self'` already covers the chat.

- nginx: paste `deploy/nginx-same-origin.conf` into the site's `server { }` block.
- Apache: paste `deploy/apache.conf` into the site's `<VirtualHost>` (modules: `proxy proxy_http headers`).

**Its own domain.** Use `deploy/nginx.conf`, with TLS, for `https://chat.example.com`. The page's CSP then
needs `connect-src https://chat.example.com` and the script host or nonce.

**The visitor's real address.** Rate limits are per visitor, so the chat server must see each visitor's
address, not the proxy's:

- The proxy sends `X-Real-IP`.
- The chat server believes that header only from `CHAT_WINDOW_TRUSTED_PROXIES`. If the web server is
  another machine, add its address there.
- Behind Cloudflare, set nginx's `real_ip_header CF-Connecting-IP` or Apache's `RemoteIPHeader CF-Connecting-IP`,
  with Cloudflare's ranges, first. Otherwise every visitor shares Cloudflare's addresses, and one rate limit.

**Streaming.** Answers stream as server-sent events. The snippets turn off proxy buffering and compression
for this path. Keep any CDN from caching `/chat-window/v1/`: the server already sends `Cache-Control: no-store`
there.

## 3. Add the chat window to the pages

```html
<script src="/chat-window/chat-window.js" data-site="mysite" defer></script>
```

- **The server address.** The chat window finds its server from where the script was loaded, so the
  same-domain path just works.
- **PHP sites.** `examples/embed.php` writes the tag, including the request's CSP nonce.
- **Nonce-based CSPs.** A CSP with `'strict-dynamic'` runs only scripts carrying that request's nonce, so
  the tag needs `nonce="..."`.

## 4. Check before going live

1. **`chat-window doctor SITE` passes on the production host.** It checks:
   - the settings;
   - Ollama, and that the models are pulled;
   - the index age;
   - one real answer, timed;
   - whether each model is on the GPU.
2. **The question set passes on the production host and model:** `chat-window eval SITE FILE`. Its
   `first_token_s_median` is the wait visitors will feel.
3. **The origin check holds.** From outside:
   - `curl -i https://example.com/chat-window/v1/sites/SITE` returns 403;
   - with `-H 'Origin: https://example.com'`, it returns 200.
4. **Rate limits use real addresses.** Seven questions within a minute from one address: the seventh gets
   "Please wait a minute", and a second address isn't affected.
5. **The privacy policy mentions the chat**; see [privacy.md](privacy.md).

## Hardware notes

- **Small GPUs (4 GB).** A 3B chat model needs about 2.4 GB at the default 4,096-token context, and
  `nomic-embed-text` about 0.4 GB, so both fit on a 4 GB card. Set `embed_on_gpu = true` to embed there too.
  Index builds are much faster on a GPU.
- **GPU support.** After the first question, `chat-window doctor` shows where each model is loaded. If a
  model you expect on the GPU shows 0%, the installed Ollama build may not support that card. Check its
  release notes for supported GPU generations.
- **CPU only.** It works, but the first word of each answer can take ten seconds or more, and index builds
  can take a long time. Measure with `doctor`.
