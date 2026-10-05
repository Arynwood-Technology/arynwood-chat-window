# Deploying

One server process can serve many sites. Each site has a file in the sites directory, and its own index in
the data directory.

## Layout on the host

```
/opt/arynwood-chat-window/            the code and its venv
/etc/arynwood-chat-window/sites/      one TOML file per site (clients' files never go in this repo)
/etc/arynwood-chat-window/env         CHAT_WINDOW_SECRET and other settings, mode 600
/var/lib/arynwood-chat-window/        indexes and the chat log
```

```bash
sudo useradd --system --home /var/lib/arynwood-chat-window --create-home chatwindow
sudo git clone https://github.com/Arynwood-Technology/arynwood-chat-window /opt/arynwood-chat-window
sudo python3 -m venv /opt/arynwood-chat-window/.venv
sudo /opt/arynwood-chat-window/.venv/bin/pip install /opt/arynwood-chat-window
sudo install -d -m 755 /etc/arynwood-chat-window/sites
sudo install -m 600 deploy/chat-window.env.example /etc/arynwood-chat-window/env   # then set the secret
sudo cp deploy/chat-window.service deploy/chat-window-index@.service deploy/chat-window-index@.timer \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start chat-window-index@mysite.service     # the first index; watch: journalctl -u chat-window-index@mysite
sudo systemctl enable --now chat-window chat-window-index@mysite.timer
```

The timer rebuilds a site's index every night, so changed prices or pages reach the chat within a day.
The server picks up a rebuilt index without a restart.

## Ollama

Run Ollama on the same host, listening only on `127.0.0.1`. Pull the chat and embedding models named in the
site files. With a small graphics card:

- Keep `embed_on_gpu = false` (the default). Embeddings then run on the CPU, which takes about a third of a
  second per question, and the card's memory stays free for the chat model.
- After the first question, `ollama ps` should show the chat model at `100% GPU`. If it shows CPU, the card
  isn't being used: check that the installed Ollama still supports that GPU generation.
- Llama 3.2 3B at the default 4,096-token context needs about 3 GB of video memory.

## Putting it on the web

The server listens on `127.0.0.1:8790`. Put a TLS reverse proxy in front of it:

- **nginx**: `deploy/nginx.conf` is a server block. It turns off buffering (answers stream) and limits
  request size. It passes the real visitor address in `X-Real-IP`, which the server believes only from
  `CHAT_WINDOW_TRUSTED_PROXIES`.
- **Behind Cloudflare**: set nginx's `real_ip_header CF-Connecting-IP` with Cloudflare's address ranges
  (`set_real_ip_from`), so `$remote_addr` is the visitor's address, not Cloudflare's. Otherwise every visitor
  shares one rate limit.

## On the website

- **The embed tag.** Add `<script src="https://chat.example.com/chat-window.js" data-site="mysite" defer></script>`
  to the pages that should show the chat.
- **CSP.** If the site sends a Content Security Policy, add `https://chat.example.com` to `connect-src`. For
  the script, either add the same origin to `script-src`, or put the page's nonce on the tag; with
  `'strict-dynamic'`, the nonce alone is enough.
- **Same-origin option.** Alternatively, proxy `/chat-window/` on the site's own server to the chat server
  and use `data-endpoint="https://example.com/chat-window"`. Then `'self'` covers everything.

## Checks before going live

1. **The question set passes.** `chat-window eval SITE FILE` passes on the production host, with the
   production model. Its `first_token_s_median` is the speed visitors will feel.
2. **The privacy policy is ready.** It mentions the chat and its retention; see [privacy.md](privacy.md).
3. **The origin check holds.** `curl -i https://chat.example.com/v1/sites/SITE` returns 403 without an
   `Origin` header, and 200 with the site's origin.
4. **Rate limits engage.** Send seven questions within a minute from one address; the seventh gets "Please
   wait a minute".
