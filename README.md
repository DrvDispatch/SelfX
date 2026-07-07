# SelfX

SelfX is a self-hosted, modular utility suite: upload a file, pick a tool, a worker
processes it, download the result. Local-first — no external calls by default, your
files never leave your machine. Multi-user with JWT auth, an admin panel, per-user
rate limits, and automatic file retention cleanup.

## Tools

| Tool | What it does | Engine | Queue |
|------|--------------|--------|-------|
| `pdf-merge` | Merge PDFs (2+ files, upload order) | pikepdf | default |
| `pdf-split` | Split PDF by page ranges, or burst every page | pikepdf | default |
| `pdf-compress` | Compress PDF (screen/ebook/printer quality) | Ghostscript | default |
| `pdf-to-docx` | PDF → Word | pdf2docx | heavy |
| `office-convert` | Office/HTML/MD → PDF | Gotenberg | default |
| `pandoc-convert` | Markup conversion (pdf/docx/html/md/epub/odt) | Pandoc | default |
| `image-convert` | Image convert/resize (png/jpg/webp/avif/bmp/tiff) | Pillow | default |
| `media-convert` | Audio/Video convert (mp4/webm/mp3/opus/wav/flac/gif) | ffmpeg | heavy |
| `metadata-remove` | Strip metadata from images/PDF/office files | exiftool | default |
| `ocr-pdf` | OCR → searchable PDF | ocrmypdf | heavy |
| `transcribe` | Transcribe audio/video (txt/srt/vtt/json) | faster-whisper | heavy |
| `ai-summarize` | AI summary of a document | Ollama | heavy |
| `doc-qa` | Ask a question about a document | Ollama | heavy |
| `archive-compress` | Compress files to zip/7z | zipfile/py7zr | default |
| `archive-extract` | Extract zip/7z/tar safely (bomb/traversal guards) | stdlib/py7zr | default |
| `qr-generate` | QR code from text (png/svg) | segno | default |

`ai-summarize`, `doc-qa` need the `ai` profile (Ollama); `transcribe` runs on CPU by
default and uses CUDA with the GPU override.

## Architecture

```
                          ┌──────────────────────── docker network ────────────────────────┐
                          │                                                                │
 Browser ──:8080──▶  web (nginx) ──/api/──▶  api (FastAPI :8000) ──┬──▶ db (postgres)      │
      │                   │  serves SPA                            ├──▶ redis (RQ queues)  │
      │                   │                                        └──▶ gotenberg :3000    │
 (proxy profile)          │                                                                │
 caddy :80/:443 ──────────┘              worker (same image as api) ◀── redis              │
                          │                 │  runs tools: ffmpeg, gs,                     │
                          │                 │  ocrmypdf, pandoc, whisper…                  │
                          │                 ├──▶ ollama :11434   (ai profile)              │
                          │                 └──▶ /data volume  (shared with api)           │
                          │                                                                │
 Browser ──:8081──▶  stirling (extras profile, standalone PDF editor GUI)                  │
                          └────────────────────────────────────────────────────────────────┘
```

Only `web` publishes a port in the core stack; everything else is internal.

## Quickstart

Requirements: Docker Engine with the compose plugin (or Docker Desktop).

```bash
cp .env.example .env
# edit .env: set SELFX_SECRET_KEY (e.g. `openssl rand -hex 32`) and SELFX_ADMIN_PASSWORD
docker compose up -d --build
```

Open <http://localhost:8080> and log in with the bootstrap admin
(`SELFX_ADMIN_USER` / `SELFX_ADMIN_PASSWORD` from `.env` — created on first start
while the users table is empty).

### Optional profiles

```bash
docker compose --profile ai up -d          # Ollama → enables ai-summarize / doc-qa
docker compose --profile extras up -d      # Stirling-PDF GUI on http://localhost:8081
docker compose --profile security up -d    # ClamAV upload scanning (set CLAMAV_ENABLED=true)
docker compose --profile proxy up -d       # Caddy TLS proxy for a VPS (see deploy/vps.md)
```

Profiles combine: `docker compose --profile ai --profile extras up -d --build`.

### Pull an Ollama model (required once for the AI tools)

```bash
docker compose exec ollama ollama pull qwen3:8b   # or whatever OLLAMA_MODEL is set to
```

### GPU acceleration (NVIDIA)

With the NVIDIA Container Toolkit installed:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile ai up -d --build
```

This reserves the GPU for `worker` + `ollama` and switches whisper to
`WHISPER_DEVICE=cuda` / `WHISPER_COMPUTE=float16`.

## Local development

Run only the backing services from compose, plus a local override to expose their
ports (compose auto-loads `docker-compose.override.yml`; it is gitignored):

```yaml
# docker-compose.override.yml
services:
  db:
    ports: ["127.0.0.1:5432:5432"]
  redis:
    ports: ["127.0.0.1:6379:6379"]
```

```bash
docker compose up -d db redis gotenberg
```

**Server** (Python 3.12):

```bash
cd server
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export SELFX_SECRET_KEY=dev-secret-not-for-prod
export DATABASE_URL=postgresql+psycopg://selfx:selfx@localhost:5432/selfx
export REDIS_URL=redis://localhost:6379/0
export DATA_DIR=$PWD/../data
uvicorn app.main:app --reload --port 8000    # API
python -m app.worker                          # worker, second terminal, same env
```

**Web** (Node 20+):

```bash
cd web
npm install
npm run dev        # http://localhost:5173, /api proxied to http://localhost:8000
```

## Troubleshooting

- **Port already in use** — the stack publishes `8080` (web), `8081` (stirling,
  extras) and `80`/`443` (caddy, proxy). Change the host side of the mapping in
  `docker-compose.yml` if something else owns them.
- **`api` never becomes healthy** — `docker compose logs api`. Most common: default
  `SELFX_SECRET_KEY` (startup fails loudly on purpose), or db credentials in
  `DATABASE_URL` not matching `POSTGRES_*`.
- **AI tools listed as unavailable** — the `ai` profile isn't running, or no model is
  pulled yet: `docker compose exec ollama ollama pull qwen3:8b`. Model pulls are
  several GB; watch `docker compose logs -f ollama`.
- **First transcription is slow** — faster-whisper downloads `WHISPER_MODEL` on first
  use inside the worker; subsequent runs are fast.
- **Worker killed / jobs die on big media or AI jobs** — the worker has a hard memory
  cap (`WORKER_MEM_LIMIT`, default 6g). Raise it, or use a smaller `WHISPER_MODEL` /
  `OLLAMA_MODEL`.
- **ClamAV rejects everything right after start** — clamd needs a few minutes to
  download signatures on first boot; check `docker compose logs clamav`.
- **Uploads fail with 413** — file exceeds `MAX_UPLOAD_MB` (default 512).

## Adding a tool

Every tool is a single Python file in `server/app/tools/` — a `Tool` subclass with a
`@register` decorator. It is auto-discovered at startup: the API lists it, the
frontend renders its form from `params_schema`, and the worker runs it. No other file
needs editing. Full walkthrough (with a working `video-thumbnail` ffmpeg example):
[docs/ADDING_TOOLS.md](docs/ADDING_TOOLS.md).

## Deployment on a VPS

See [deploy/vps.md](deploy/vps.md): DNS, `.env` hardening, `--profile proxy` for
automatic TLS via Caddy, and firewall notes.
