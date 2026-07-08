#!/usr/bin/env bash
# Stop the SelfX app processes (leaves Postgres/Redis/Ollama running).
echo "[selfx-stop] stopping api + worker + quick-tools"
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "app.worker" 2>/dev/null || true
pkill -f "http.server 809" 2>/dev/null || true
echo "[selfx-stop] done (datastores + ollama left running; use 'wsl --shutdown' to stop everything)"
