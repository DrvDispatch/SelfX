# SelfX — Technical Contract (SPEC)

This document is the **single source of truth** for names, paths, ports, env vars, API
shapes, and interfaces. All components (server, web, infra) MUST follow it exactly.
If a detail is not specified here, choose the simplest conventional option and keep it
consistent with the patterns below.

SelfX is a self-hosted, modular utility suite: upload a file → pick a tool → a worker
processes it → download the result. Local-first, no external calls by default.

---

## 1. Repository layout

```
C:\SelfX
├── docker-compose.yml          # core stack + optional profiles
├── docker-compose.gpu.yml      # GPU override (worker + ollama)
├── .env.example                # every env var below, with defaults + comments
├── .gitignore
├── .dockerignore
├── README.md                   # quickstart, tool list, adding tools, troubleshooting
├── docs/
│   ├── SPEC.md                 # this file
│   ├── REPORT.md               # full technical report (written separately)
│   └── ADDING_TOOLS.md         # how to write a new tool adapter
├── server/                     # Python: API + worker share ONE image / ONE package
│   ├── Dockerfile              # multi-stage; final image runs as non-root `selfx`
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── main.py             # FastAPI app factory, routers, startup tasks
│       ├── config.py           # pydantic-settings Settings, reads env vars
│       ├── db.py               # SQLAlchemy engine/session, init_db()
│       ├── models.py           # User, Job, File ORM models
│       ├── schemas.py          # Pydantic response/request models
│       ├── auth.py             # bcrypt hashing, JWT create/verify, deps
│       ├── storage.py          # save_upload, file paths, retention cleanup
│       ├── queueing.py         # RQ queues + enqueue_job(job_id, queue_name)
│       ├── worker.py           # RQ worker entrypoint + run_tool(job_id)
│       ├── cleanup.py          # expired file/job purge logic
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── auth.py         # /auth/login, /auth/me
│       │   ├── tools.py        # /tools
│       │   ├── files.py        # /files upload + download
│       │   ├── jobs.py         # /jobs CRUD
│       │   └── admin.py        # /admin/*
│       └── tools/
│           ├── __init__.py     # discover(): imports every module in this package
│           ├── base.py         # Tool base class, ToolContext, run_cmd helper
│           ├── registry.py     # @register decorator, get_tool(), all_tools()
│           └── <one file per tool, see §8>
├── web/                        # React SPA
│   ├── Dockerfile              # node build stage → nginx:alpine serving /usr/share/nginx/html
│   ├── nginx.conf              # serves SPA + proxies /api/ → http://api:8000
│   ├── package.json            # react, react-dom, react-router-dom, vite, typescript, tailwindcss
│   ├── vite.config.ts          # dev proxy: /api → http://localhost:8000
│   ├── index.html
│   └── src/
│       ├── main.tsx, App.tsx
│       ├── api.ts              # typed fetch client, auth header, error handling
│       ├── types.ts            # ToolInfo, Job, FileInfo, User types (mirror §5 shapes)
│       ├── auth.tsx            # token storage (localStorage), AuthContext, guard
│       ├── components/         # Layout, ToolCard, ParamsForm, FileDrop, JobRow, StatusBadge
│       └── pages/              # Login, Dashboard, ToolPage, Jobs, Admin
└── deploy/
    ├── Caddyfile               # optional VPS TLS proxy (profile: proxy)
    └── vps.md                  # short VPS notes (long version lives in REPORT.md)
```

## 2. Services, ports, networks (docker-compose)

| service    | image / build                  | port (host)         | profile   | notes |
|------------|--------------------------------|---------------------|-----------|-------|
| `web`      | build `./web`                  | `8080:80`           | (core)    | nginx: SPA + `/api/` proxy → `api:8000`; the ONLY core service with a published port |
| `api`      | build `./server`               | none (internal)     | (core)    | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `worker`   | same build as api              | none                | (core)    | command: `python -m app.worker`; consumes queues `default,heavy` |
| `db`       | `pgvector/pgvector:pg16`       | none                | (core)    | volume `pgdata`; healthcheck `pg_isready` |
| `redis`    | `redis:7-alpine`               | none                | (core)    | volume not needed; `--maxmemory-policy noeviction` |
| `gotenberg`| `gotenberg/gotenberg:8`        | none                | (core)    | document conversion API |
| `ollama`   | `ollama/ollama`                | none                | `ai`      | volume `ollama`; api+worker reach it at `http://ollama:11434` |
| `stirling` | `stirlingtools/stirling-pdf:latest` | `8081:8080`    | `extras`  | full PDF editor GUI, linked from dashboard |
| `clamav`   | `clamav/clamav:stable`         | none                | `security`| optional upload scanning via clamd TCP 3310 |
| `caddy`    | `caddy:2`                      | `80:80`, `443:443`  | `proxy`   | VPS TLS; proxies to `web:80` |

Networks: single default bridge network is fine, BUT set `internal: true` is NOT used
(worker may need egress for model downloads); instead: no published ports except web
(and stirling/caddy in their profiles). All services `restart: unless-stopped`.
Volumes: `pgdata`, `selfx_data` (mounted at `/data` in api + worker), `ollama`.
api/worker containers run as non-root and get `security_opt: [no-new-privileges:true]`.
worker gets `mem_limit: ${WORKER_MEM_LIMIT:-6g}` and `shm_size: 1g`.

## 3. Environment variables (all read via `app/config.py`; prefix-less)

```
# --- core ---
SELFX_SECRET_KEY=change-me-long-random          # JWT signing (HS256). REQUIRED.
SELFX_ADMIN_USER=admin                          # bootstrap admin (created if users table empty)
SELFX_ADMIN_PASSWORD=change-me                  # bootstrap admin password
DATABASE_URL=postgresql+psycopg://selfx:selfx@db:5432/selfx
REDIS_URL=redis://redis:6379/0
DATA_DIR=/data                                  # uploads/ and outputs/ live under this
# --- limits & retention ---
MAX_UPLOAD_MB=512
FILE_RETENTION_HOURS=24                         # 0 = keep forever
JOB_TIMEOUT_SECONDS=1800                        # per-job hard timeout (RQ)
RATE_LIMIT_PER_MINUTE=60                        # per-user API rate limit (job creation & upload)
# --- integrations ---
GOTENBERG_URL=http://gotenberg:3000
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen3:8b                           # default LLM for summarize/doc-qa
WHISPER_MODEL=small                             # faster-whisper model size
WHISPER_DEVICE=cpu                              # cpu | cuda
WHISPER_COMPUTE=int8                            # int8 (cpu) | float16 (gpu)
CLAMAV_ENABLED=false
CLAMAV_HOST=clamav
CLAMAV_PORT=3310
# --- postgres container ---
POSTGRES_USER=selfx
POSTGRES_PASSWORD=selfx
POSTGRES_DB=selfx
```

## 4. Database schema (SQLAlchemy models; `init_db()` runs `create_all` on startup)

```
users:  id UUID pk (default uuid4) | username str unique | password_hash str
        | is_admin bool default false | disabled bool default false
        | created_at datetime (UTC, default now)

jobs:   id UUID pk | user_id UUID fk users.id | tool str (slug)
        | status str: queued|running|done|error|canceled  (default queued)
        | progress float 0..1 default 0 | message str nullable (current step / error detail)
        | params JSONB default {} | error text nullable
        | created_at | started_at nullable | finished_at nullable
        | rq_job_id str nullable

files:  id UUID pk | user_id UUID fk | job_id UUID fk jobs.id nullable
        | kind str: upload|output | orig_name str | stored_path str (relative to DATA_DIR)
        | size bigint | mime str | created_at | expires_at datetime nullable
```

On-disk layout: `/data/uploads/<file_uuid><suffix>` and `/data/outputs/<job_uuid>/<orig_name>`.
Stored filenames NEVER come from user input except the basename recorded in DB
(`orig_name` is sanitized: strip path separators, control chars, max 255 chars).

## 5. HTTP API (all JSON; base path `/api/v1`; errors: `{"detail": "..."}` with 4xx/5xx)

Auth: `Authorization: Bearer <jwt>` on everything except `/auth/login` and `/healthz`.
JWT: HS256, `sub`=user id, `exp` = now + 7 days.

```
GET  /api/v1/healthz                  → {"status":"ok"}   (also checks db+redis, 503 if down)

POST /api/v1/auth/login               {username, password} → {access_token, token_type:"bearer",
                                       user: {id, username, is_admin}}
GET  /api/v1/auth/me                  → {id, username, is_admin}

GET  /api/v1/tools                    → [ToolInfo]
  ToolInfo = {slug, name, category, description, accepts: [".pdf",...] (empty = no file input),
              multi_file: bool, min_files: int, params_schema: <JSON Schema object>,
              queue: "default"|"heavy", available: bool, unavailable_reason: str|null}
  `available:false` when a dependency is down/not configured (e.g. Ollama off) — still listed.

POST /api/v1/files                    multipart field "file" → FileInfo
  FileInfo = {id, orig_name, size, mime, created_at, expires_at}
  413 if over MAX_UPLOAD_MB. If CLAMAV_ENABLED, scan before accepting; 422 on virus.
GET  /api/v1/files/{id}/download      → streamed file (Content-Disposition attachment,
                                        original filename). Owner or admin only.

POST /api/v1/jobs                     {tool: slug, file_ids: [uuid], params: {}} → Job (201)
  Validates: tool exists+available, file count vs min_files/multi_file, extensions vs accepts,
  params vs params_schema (jsonschema lib). Enqueues to the tool's queue. Rate-limited.
GET  /api/v1/jobs?limit=50&offset=0   → {items: [Job], total}   (own jobs, newest first)
GET  /api/v1/jobs/{id}                → Job
  Job = {id, tool, status, progress, message, params, error, created_at, started_at,
         finished_at, input_files: [FileInfo], output_files: [FileInfo]}
POST /api/v1/jobs/{id}/cancel         → Job (best-effort: only queued jobs cancel cleanly)
DELETE /api/v1/jobs/{id}              → 204 (removes job record + its output files)

GET  /api/v1/admin/stats              → {users, jobs_total, jobs_by_status: {}, disk_used_bytes,
                                         queue_depth: {default, heavy}}
GET  /api/v1/admin/users              → [User]
POST /api/v1/admin/users              {username, password, is_admin} → User
PATCH /api/v1/admin/users/{id}        {password?, is_admin?, disabled?} → User
DELETE /api/v1/admin/users/{id}       → 204
GET  /api/v1/admin/jobs?limit&offset  → all users' jobs
```

## 6. Tool adapter interface (server/app/tools/base.py + registry.py)

```python
class ToolContext:
    job_id: uuid.UUID
    input_paths: list[Path]      # resolved absolute paths of input files (read-only intent)
    params: dict                  # already validated against params_schema
    workdir: Path                 # per-job scratch dir, wiped after run
    output_dir: Path              # /data/outputs/<job_id>/ — everything left here becomes a result
    def progress(self, fraction: float, message: str = "") -> None: ...   # writes to jobs row
    def run_cmd(self, args: list[str], timeout: int | None = None, **kw) -> subprocess.CompletedProcess:
        # ALWAYS list-args, shell=False, cwd=workdir, captures output,
        # raises ToolError with stderr tail on nonzero exit. No user string ever
        # becomes an argv flag: user-controlled values are passed as file paths or
        # validated enum/number params only.

class Tool:                       # subclass + @register
    slug: str; name: str; category: str; description: str
    accepts: list[str] = []       # allowed input extensions, [] = no file input
    multi_file: bool = False
    min_files: int = 1            # 0 for param-only tools (e.g. QR)
    params_schema: dict = {"type":"object","properties":{}}
    queue: str = "default"        # "heavy" for media/AI
    def available(self) -> tuple[bool, str | None]: return True, None
    def run(self, ctx: ToolContext) -> None: ...   # writes outputs into ctx.output_dir

@register  # adds class to REGISTRY dict keyed by slug; raises on duplicate slug
```

Worker flow (`run_tool(job_id)` executed by RQ):
1. load job, mark `running`, `started_at=now`
2. build ToolContext (create workdir under `/data/tmp/<job_id>`, output_dir)
3. `tool.run(ctx)`; on ToolError/Exception → status `error`, `error` = safe message (never raw paths/tracebacks to user; full traceback to logs)
4. register every file in output_dir as `files(kind=output, job_id=...)` with expires_at
5. mark `done`, progress 1.0; always wipe workdir in `finally`

## 7. Params schema → frontend form

`params_schema` is standard JSON Schema (draft 7 subset). Frontend renders:
`string` → text input (`format:"multiline"` → textarea), `enum` → select,
`number`/`integer` → number input (min/max), `boolean` → checkbox.
`default` values pre-filled; `title` and `description` shown as label/help.
Backend re-validates with `jsonschema` — frontend rendering is convenience only.

## 8. Tools to scaffold (slug → engine → queue)

| slug | name | engine | queue | params (summary) |
|------|------|--------|-------|-------------------|
| `pdf-merge` | Merge PDFs | pikepdf | default | (none; ordered by upload order), multi_file, min 2 |
| `pdf-split` | Split PDF | pikepdf | default | `pages` string e.g. "1-3,7" (empty = burst every page into separate pdf, zipped) |
| `pdf-compress` | Compress PDF | ghostscript `gs` | default | `quality` enum screen/ebook/printer default ebook |
| `pdf-to-docx` | PDF → Word | pdf2docx | heavy | none |
| `office-convert` | Office/HTML/MD → PDF | Gotenberg HTTP API | default | `landscape` bool; accepts .docx .doc .odt .pptx .xlsx .html .md .txt .rtf |
| `pandoc-convert` | Markup convert | pandoc CLI | default | `to` enum: pdf/docx/html/md/epub/odt; accepts .md .html .docx .odt .epub .tex .rst |
| `image-convert` | Image convert/resize | Pillow (+pillow-heif) | default | `format` enum png/jpg/webp/avif/bmp/tiff; `quality` 1-100 default 85; `max_width` int optional; `strip_metadata` bool default true |
| `media-convert` | Audio/Video convert | ffmpeg CLI | heavy | `preset` enum mp4-h264/webm-vp9/mp3/opus/wav/flac/gif; `crf` int optional |
| `metadata-remove` | Remove metadata | exiftool `-all=` | default | none; accepts images + pdf + office |
| `ocr-pdf` | OCR (searchable PDF) | ocrmypdf | heavy | `language` enum eng/deu/fra/spa/... default eng; `deskew` bool |
| `transcribe` | Transcribe audio/video | faster-whisper | heavy | `language` string default "auto"; `output` enum txt/srt/vtt/json |
| `ai-summarize` | AI Summarize | Ollama /api/chat | heavy | `length` enum short/medium/detailed; `language` enum auto/english/...; accepts .pdf .txt .md .docx |
| `doc-qa` | Ask a document | Ollama /api/chat | heavy | `question` string required; same accepts as summarize |
| `archive-compress` | Compress files | zipfile/py7zr | default | `format` enum zip/7z; multi_file min 1 |
| `archive-extract` | Extract archive | zipfile/tarfile/py7zr + guards | default | accepts .zip .7z .tar .gz .tgz .tar.gz; guards: path traversal, >10k entries, >2GB expanded, ratio >100× |
| `qr-generate` | QR code | segno | default | `text` string required; `format` enum png/svg; `scale` int default 8; min_files 0 |

Notes: `ai-summarize`/`doc-qa` extract text via pypdf (pdf), python-docx (docx), or raw read
(txt/md); truncate to ~24k chars with a note; chat via `POST {OLLAMA_URL}/api/chat`
`{"model": OLLAMA_MODEL, "messages":[...], "stream": false}`. `available()` checks Ollama
reachability. ffmpeg progress: parse `-progress pipe:1` key=value output → ctx.progress().
gs/ocrmypdf/pandoc/exiftool/ffmpeg installed via apt in server/Dockerfile
(`ghostscript tesseract-ocr tesseract-ocr-eng qpdf pandoc exiftool ffmpeg libmagic1`).

## 9. Frontend pages & behavior

- **Login** (`/login`): username/password → store token in localStorage; redirect to `/`.
- **Dashboard** (`/`): tool cards grouped by category (`pdf`, `documents`, `images`,
  `media`, `ai`, `utilities`); search box filters by name/description; unavailable tools
  greyed with reason tooltip.
- **Tool page** (`/tool/:slug`): drag-drop file zone (respects accepts/multi_file; hidden
  when min_files=0), ParamsForm from params_schema, Run button → POST /files per file →
  POST /jobs → navigate to `/jobs?highlight=<id>`.
- **Jobs** (`/jobs`): table (tool, status badge, progress bar, created, duration, actions:
  download each output / cancel / delete). Poll `GET /jobs` every 2s while any job is
  queued/running; stop polling otherwise.
- **Admin** (`/admin`, admin-only): stats cards + users table (create/disable/delete/reset pw).
- Styling: Tailwind only, dark theme default, no component library. Keep it clean and dense.
  Vite dev proxy `/api` → `http://localhost:8000` so `npm run dev` works against compose api.

## 10. Security requirements (must be implemented, not just documented)

- bcrypt password hashing (`bcrypt` package), constant-time verify.
- JWT secret from env; startup fails loudly if SELFX_SECRET_KEY is default/empty in
  non-debug mode.
- Upload size enforced while streaming to disk (reject beyond MAX_UPLOAD_MB, don't buffer in RAM).
- File type check: extension must match tool `accepts`; MIME sniffed with python-magic
  logged (mismatch → warning + reject for archives).
- All subprocess calls: list args, `shell=False`, timeout, output confined to workdir/output_dir.
- Download/delete endpoints check ownership (or admin).
- Retention: hourly asyncio task in api process deletes expired files (disk + rows) and
  jobs older than 30 days; also purges orphaned tmp dirs.
- Rate limit: slowapi, per-user key (fallback IP), on POST /files and POST /jobs.
- Non-root containers; no published ports for internal services; `no-new-privileges`.
- Archive extraction guards per §8. ImageMagick is NOT installed (Pillow only) — one less
  attack surface.
- CORS: same-origin via nginx proxy in prod; in dev, FastAPI CORS middleware allows
  http://localhost:5173.

## 11. Coding conventions

- Python 3.12, type hints everywhere, Pydantic v2, SQLAlchemy 2.0 style (Mapped[...]).
- No async DB (sync SQLAlchemy + `def` endpoints is fine at this scale; uvicorn threadpool).
- Errors: raise `HTTPException` in routes; `ToolError("user-safe message")` in tools.
- Logging: std `logging`, one line per job state change, JSON not required.
- requirements.txt pinned to major versions (e.g. `fastapi>=0.115,<1`).
- Frontend: TypeScript strict, small components, no state library (React context + hooks).
- Every file ≤ ~300 lines where reasonable; split rather than grow.
