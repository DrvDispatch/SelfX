#!/usr/bin/env bash
# Idempotent starter for the whole SelfX stack inside WSL2. Safe to run repeatedly:
# every service is only (re)started if it isn't already running. Invoked at Windows
# logon by the "SelfX" scheduled task, or manually via deploy/Start-SelfX.bat.
set -u

ENV_FILE="/root/selfx.env"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"
VENV=/root/selfx-venv/bin
SERVER=/mnt/c/SelfX/server

log() { echo "[selfx-start] $*"; }

# --- datastores ---
service postgresql start >/dev/null 2>&1 || pg_ctlcluster "$(ls /etc/postgresql 2>/dev/null | head -1)" main start >/dev/null 2>&1 || true
service redis-server start >/dev/null 2>&1 || redis-server --daemonize yes >/dev/null 2>&1 || true

# --- clamav daemon (optional) ---
if command -v clamd >/dev/null 2>&1 && ! pgrep -x clamd >/dev/null 2>&1; then
  mkdir -p /run/clamav && chown clamav:clamav /run/clamav 2>/dev/null || true
  nohup clamd >/dev/null 2>&1 & disown
fi

# --- Ollama (inherits OLLAMA_MODELS + OLLAMA_KEEP_ALIVE from selfx.env) ---
if ! pgrep -f "ollama serve" >/dev/null 2>&1; then
  : "${OLLAMA_MODELS:=/usr/share/ollama/.ollama/models}"
  export OLLAMA_MODELS
  nohup ollama serve >/root/ollama.log 2>&1 & disown
  sleep 3
fi

# --- API + worker ---
cd "$SERVER" || { log "server dir missing"; exit 1; }
if ! pgrep -f "uvicorn app.main:app" >/dev/null 2>&1; then
  nohup "$VENV/uvicorn" app.main:app --host 0.0.0.0 --port 8000 >/root/selfx-api.log 2>&1 & disown
fi
if ! pgrep -f "app.worker" >/dev/null 2>&1; then
  nohup "$VENV/python" -m app.worker >/root/selfx-worker.log 2>&1 & disown
fi

# --- Quick Tools static sites ---
serve_qt() {
  local port="$1" dir="$2"
  [ -d "$dir" ] || return 0
  pgrep -f "http.server $port" >/dev/null 2>&1 && return 0
  (cd "$dir" && nohup python3 -m http.server "$port" --bind 0.0.0.0 >"/tmp/qt_$port.log" 2>&1 & disown)
}
serve_qt 8091 /srv/quicktools/cyberchef
serve_qt 8092 /srv/quicktools/it-tools/dist
serve_qt 8093 /srv/quicktools/omni-tools/dist

sleep 2
IP="$(hostname -I | awk '{print $1}')"
log "SelfX is up  ->  http://${IP}:8000   (health: $(curl -s -m5 http://127.0.0.1:8000/api/v1/healthz 2>/dev/null || echo 'starting'))"
