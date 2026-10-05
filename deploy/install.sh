#!/usr/bin/env bash
# Install or upgrade Arynwood Chat Window as a systemd service on Debian or Ubuntu.
#
#   sudo deploy/install.sh --site path/to/mysite.toml [--evals path/to/mysite.jsonl]
#                          [--host 127.0.0.1] [--port 8790] [--trusted-proxies "127.0.0.1,::1"]
#                          [--no-start]
#
# Safe to run again: it upgrades the code and keeps the secret, the chat log and the indexes.
# Run it once per site; every site is served by the same service.
# --no-start installs files only (no systemd, no Ollama check), for containers and dry runs.
set -euo pipefail

PREFIX=${CHAT_WINDOW_PREFIX:-/opt/arynwood-chat-window}
ETC=${CHAT_WINDOW_ETC:-/etc/arynwood-chat-window}
DATA=${CHAT_WINDOW_VAR:-/var/lib/arynwood-chat-window}
ACCOUNT=chatwindow
SRC="$(cd "$(dirname "$0")/.." && pwd)"

SITE_FILE="" EVALS_FILE="" HOST="" PORT="" PROXIES="" START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --site) SITE_FILE=$2; shift 2 ;;
    --evals) EVALS_FILE=$2; shift 2 ;;
    --host) HOST=$2; shift 2 ;;
    --port) PORT=$2; shift 2 ;;
    --trusted-proxies) PROXIES=$2; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo)"
[ -n "$SITE_FILE" ] || die "--site is required"
[ -f "$SITE_FILE" ] || die "no such file: $SITE_FILE"
SITE=$(basename "$SITE_FILE" .toml)
[ -z "$EVALS_FILE" ] || [ -f "$EVALS_FILE" ] || die "no such file: $EVALS_FILE"
command -v python3 >/dev/null || die "python3 is missing: apt install python3 python3-venv"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10 or newer is needed"
python3 -c 'import ensurepip' 2>/dev/null || die "python3-venv is missing: apt install python3-venv"

say "Account and directories"
if ! id -u "$ACCOUNT" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin "$ACCOUNT"
fi
install -d -m 755 "$PREFIX" "$ETC" "$ETC/sites" "$ETC/evals"
install -d -m 750 -o "$ACCOUNT" -g "$ACCOUNT" "$DATA"

say "Code ($PREFIX)"
rm -rf "$PREFIX/src.new"
install -d "$PREFIX/src.new"
tar -C "$SRC" --exclude=.git --exclude=.venv --exclude=data --exclude=sites --exclude=evals \
    --exclude='*.sqlite' --exclude=__pycache__ -cf - . | tar -C "$PREFIX/src.new" -xf -
rm -rf "$PREFIX/src" && mv "$PREFIX/src.new" "$PREFIX/src"
[ -x "$PREFIX/venv/bin/python" ] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet --upgrade "$PREFIX/src"

say "Site $SITE"
"$PREFIX/venv/bin/python" - "$SITE_FILE" <<'PY'
import sys
from pathlib import Path
from chat_window.config import load_site
site = load_site(Path(sys.argv[1]))
print(f"   {site.name}: origins {', '.join(site.allowed_origins)}; chat model {site.model.chat}")
PY
install -m 644 "$SITE_FILE" "$ETC/sites/$SITE.toml"
[ -z "$EVALS_FILE" ] || install -m 644 "$EVALS_FILE" "$ETC/evals/$SITE.jsonl"

set_env() {   # set_env KEY VALUE: replace the line or append it
  if grep -q "^$1=" "$ETC/env"; then sed -i "s|^$1=.*|$1=$2|" "$ETC/env"; else echo "$1=$2" >> "$ETC/env"; fi
}
if [ ! -f "$ETC/env" ]; then
  umask 077
  cat > "$ETC/env" <<EOF
# Arynwood Chat Window settings. Keep this file private: the secret keys the visitor hashes.
CHAT_WINDOW_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
CHAT_WINDOW_SITES=$ETC/sites
CHAT_WINDOW_DATA=$DATA
CHAT_WINDOW_HOST=127.0.0.1
CHAT_WINDOW_PORT=8790
CHAT_WINDOW_TRUSTED_PROXIES=127.0.0.1,::1
CHAT_WINDOW_CLIENT_IP_HEADER=X-Real-IP
CHAT_WINDOW_MAX_CONCURRENT=1
CHAT_WINDOW_MAX_QUEUE=8
EOF
  umask 022
  echo "   wrote $ETC/env with a new secret"
fi
[ -z "$HOST" ] || set_env CHAT_WINDOW_HOST "$HOST"
[ -z "$PORT" ] || set_env CHAT_WINDOW_PORT "$PORT"
[ -z "$PROXIES" ] || set_env CHAT_WINDOW_TRUSTED_PROXIES "$PROXIES"
chmod 600 "$ETC/env"

cat > /usr/local/sbin/chat-window-admin <<EOF
#!/bin/sh
# Run chat-window as the service account with the service's settings, e.g.: chat-window-admin stats $SITE
set -a; . "$ETC/env"; set +a
cd "$DATA"
exec runuser -u $ACCOUNT -- "$PREFIX/venv/bin/chat-window" "\$@"
EOF
chmod 755 /usr/local/sbin/chat-window-admin

for unit in chat-window.service chat-window-index@.service chat-window-index@.timer; do
  sed -e "s|/opt/arynwood-chat-window|$PREFIX|g" -e "s|/etc/arynwood-chat-window|$ETC|g" \
      -e "s|/var/lib/arynwood-chat-window|$DATA|g" "$PREFIX/src/deploy/$unit" > "/etc/systemd/system/$unit.new"
  if [ "$START" -eq 1 ]; then mv "/etc/systemd/system/$unit.new" "/etc/systemd/system/$unit"
  else rm -f "/etc/systemd/system/$unit.new"; fi
done

if [ "$START" -eq 0 ]; then
  say "Installed without starting (--no-start). Next: chat-window-admin index $SITE; chat-window-admin serve"
  exit 0
fi

say "Ollama"
OLLAMA=$(set -a; . "$ETC/env"; set +a; "$PREFIX/venv/bin/python" -c "
from chat_window.config import Settings
s = Settings.from_env().load_sites()['$SITE'].model
print(s.ollama_url, s.chat, s.embed)")
read -r OLLAMA_URL CHAT_MODEL EMBED_MODEL <<<"$OLLAMA"
if ! curl -fsS "$OLLAMA_URL/api/version" >/dev/null; then
  die "Ollama isn't answering at $OLLAMA_URL. Install it (https://ollama.com/download/linux), keep it on
127.0.0.1, start it (systemctl enable --now ollama), then run this again."
fi
for model in "$CHAT_MODEL" "$EMBED_MODEL"; do
  echo "   pulling $model (skipped quickly if it's already there)"
  curl -fsS "$OLLAMA_URL/api/pull" -d "{\"model\": \"$model\", \"stream\": false}" >/dev/null
done

say "Services"
systemctl daemon-reload
echo "   building the $SITE index (reads the site's public pages; a few minutes)"
systemctl start "chat-window-index@$SITE.service"
systemctl enable --now "chat-window-index@$SITE.timer" >/dev/null
systemctl enable chat-window.service >/dev/null
systemctl restart chat-window.service

say "Checks"
chat-window-admin doctor "$SITE" || true
if [ -n "$EVALS_FILE" ]; then
  chat-window-admin eval "$SITE" "$ETC/evals/$SITE.jsonl" | tail -n 16 || true
fi

PORT_NOW=$(grep '^CHAT_WINDOW_PORT=' "$ETC/env" | cut -d= -f2)
say "Done"
cat <<EOF
The chat server is listening on $(grep '^CHAT_WINDOW_HOST=' "$ETC/env" | cut -d= -f2):$PORT_NOW.
Next:
  1. Put it behind the website: deploy/nginx-same-origin.conf or deploy/apache.conf (same domain,
     no CSP change beyond the script nonce), or deploy/nginx.conf (its own domain).
  2. Add the embed to the site's pages: examples/embed.php or examples/embed.html.
  3. Day to day: chat-window-admin stats $SITE | chat-window-admin doctor $SITE | journalctl -u chat-window
EOF
