# SelfX — Session Handoff (for Opus 4.8)

**Written:** 2026-07-07, end of the Fable 5 session, approaching usage limit.
**Read order:** this file → [SPEC.md](SPEC.md) (binding contract) → [REPORT.md](REPORT.md)
(research + rationale). Then act on §"Immediate next actions" below.

---

## 1. TL;DR of where things stand

We are building **SelfX**, a self-hosted modular "Swiss-army-knife" utility suite
(PDF / documents / images / media / OCR / AI, upload→job→worker→download). The plan is
fully researched and the scaffold is ~85% built. Two concrete gaps remain before it runs.

**DONE ✅**
- **Research**: a 15-agent workflow verified ~90 OSS projects live via `gh` on 2026-07-07
  (freshness, license, Docker, API). Full digest at
  `scratchpad/research_digest.md`
  (214 KB) and the raw task output at `...\tasks\w4nrl6dz7.output`.
- **`docs/REPORT.md`** (45 KB): the full professional report the user asked for — all 22
  required sections (exec summary, best projects, architecture, per-category integration,
  AI plan, compose, folders, API, frontend, queue, schema, storage, security, hardware,
  GPU/CPU, dev setup, VPS, roadmap, MVP, advanced, final stack, next steps, license-flag
  appendix). Consider it complete; polish only if asked.
- **`docs/SPEC.md`** (committed, `a54f740`): the binding technical contract — repo layout,
  compose topology, env vars, DB schema, full HTTP API, tool-adapter interface, the 16-tool
  table (§8), frontend behavior, security requirements. **This is the source of truth.**
- **Infra** (agent complete): `docker-compose.yml`, `docker-compose.gpu.yml`, `.env.example`,
  `.gitignore`, `.dockerignore`, `README.md`, `deploy/Caddyfile`, `deploy/vps.md`,
  `docs/ADDING_TOOLS.md`. Self-validated with `docker compose config --quiet` (base + gpu +
  all 4 profiles).
- **Web SPA** (agent complete, 26 files): Vite+React+TS strict+Tailwind v4. **`npm install`
  + `npm run build` PASS** (zero TS errors; ~210 KB JS). All 5 pages (Login, Dashboard,
  ToolPage, Jobs, Admin), schema-driven ParamsForm, api.ts covering every endpoint, nginx.conf
  proxy. (There's a committed `web/dist/` build artifact — fine to delete/gitignore.)
- **Server core** (agent complete, 25 files): `server/Dockerfile` (python:3.12-slim,
  apt CLIs, non-root `selfx`), `requirements.txt`, and all of `app/`: config, db, models,
  schemas, auth (JWT+bcrypt), storage (streamed upload + size cap), queueing, worker.py
  (full `run_tool` state machine per SPEC §6), cleanup, main.py (lifespan + hourly retention +
  bootstrap admin), `routes/*` (auth, tools, files, jobs, admin — full API incl. rate limiting,
  ownership checks, clamd INSTREAM over raw socket), and the tools **foundation**:
  `tools/base.py` (Tool/ToolContext/ToolError/run_cmd), `tools/registry.py` (@register),
  `tools/__init__.py` (`discover()` via pkgutil — auto-imports every adapter file), plus **two
  reference adapters**: `pdf_merge.py` and `qr_generate.py`.

**NOT DONE ❌ — the two gaps**
1. **The 15 remaining tool adapters were never written.** The scaffold workflow's
   `server-tools` agent (2nd stage of the server chain) started but the workflow was stopped
   before it wrote files. `server/app/tools/` currently holds ONLY `base.py`, `registry.py`,
   `__init__.py`, `pdf_merge.py`, `qr_generate.py`. **Missing** (all specified in SPEC §8):
   `pdf_split.py`, `pdf_compress.py`, `pdf_to_docx.py`, `office_convert.py`,
   `pandoc_convert.py`, `image_convert.py`, `media_convert.py`, `metadata_remove.py`,
   `ocr_pdf.py`, `transcribe.py`, `ai_summarize.py`, `doc_qa.py`, `_text_extract.py` (shared
   helper), `archive_compress.py`, `archive_extract.py`.
   → Until these exist, `GET /tools` returns only 2 tools, though README/REPORT advertise 17.
2. **The Verify phase never ran.** None of the 4 planned reviewers (contract / python /
   infra / security) executed. **No code has been reviewed or run.** The build agents
   self-reported success (web build passes, compose config validates, `py_compile` clean),
   but nothing has been end-to-end executed (`docker compose up` has NOT been tried).

**Git state:** only `docs/SPEC.md` is committed (`a54f740` on branch `master`). Everything
else — the entire scaffold, REPORT.md, this file — is **uncommitted** in the working tree.
`.gitignore` exists now, so a broad `git add .` is safe. `main` is the intended PR base;
we're on `master`.

---

## 2. Immediate next actions (in order)

1. **Write the 15 missing tool adapters** (gap #1). This is the highest-value next step.
   - Read `server/app/tools/base.py`, `registry.py`, `pdf_merge.py`, `qr_generate.py` FIRST to
     match the exact interface/idioms, then read `server/app/config.py` (how settings are read)
     and `requirements.txt` (available libs).
   - Implement each per **SPEC §8** (exact slug / engine / queue / accepts / params_schema).
     Engine notes from research are in REPORT §2 and §4. Key per-adapter reminders:
     - `office_convert`: httpx `POST {GOTENBERG_URL}/forms/libreoffice/convert`, multipart `files`.
     - `pandoc_convert`, `ocr_pdf`, `metadata_remove`, `pdf_compress`, `media_convert`: use
       `ctx.run_cmd([...])` (list argv, never shell). gs/pandoc/exiftool/ffmpeg/ocrmypdf/qpdf
       are already apt-installed in the Dockerfile (verify).
     - `media_convert`: presets-as-data (mp4-h264/webm-vp9/mp3/opus/wav/flac/gif); progress via
       `-progress pipe:1` parsed against `ffprobe` duration → `ctx.progress()`.
     - `image_convert`: Pillow + `pillow_heif.register_heif_opener()`; note Pillow may lack an
       AVIF encoder → raise ToolError telling user to pick webp if avif unsupported at runtime.
     - `transcribe`: `faster_whisper.WhisperModel(settings.whisper_model, device, compute_type)`;
       lazy module-global model cache; emit txt/srt/vtt/json with correctly formatted timestamps.
     - `ai_summarize` + `doc_qa`: shared `_text_extract.py` (pypdf / python-docx / raw read,
       ~24k-char cap); `POST {OLLAMA_URL}/api/chat {stream:false}`; `available()` pings
       `{OLLAMA_URL}/api/tags` with a 2s timeout and returns `(False, reason)` when Ollama is off.
     - `archive_extract`: ALL SPEC §8 guards — path-traversal (resolved-prefix check), ≤10k
       entries, ≤2 GiB expanded, ratio ≤100×, reject symlinks; extract to fresh dir.
   - After writing, `python -m py_compile` every new file (py3.14 is on PATH; code targets 3.12
     but must parse). Because `discover()` auto-imports, no other file needs editing.
   - **Easiest mechanical path:** re-run the stopped scaffold workflow from cache — it will
     replay the 3 finished agents instantly and re-run only the server-tools stage + reviewers:
     `Workflow({ scriptPath:
     "C:\\path\\to\\selfx-scaffold-workflow.js",
     resumeFromRunId: "wf_31d6b672-a76" })`. (Verify the cache actually replays; if the run is
     from a prior process and won't resume, just write the adapters directly — it's ~15 small files.)

2. **Run the Verify phase** (gap #2): 4 reviewers — cross-component API contract (web↔server),
   Python correctness (imports resolve, SQLAlchemy 2.0, RQ signatures, each adapter's lib usage,
   requirements coverage), infra coherence (every `config.py` env var is in `.env.example` +
   compose; Dockerfile installs every CLI the adapters call; nginx `/api` proxy has no
   double/under-prefix), and security (SPEC §10 items actually implemented). The exact reviewer
   prompts are in the scaffold workflow script (same path as above) — reuse them.

3. **Actually run it** (nothing has been executed yet): `cp .env.example .env`, set
   `SELFX_SECRET_KEY` / `SELFX_ADMIN_PASSWORD` / `POSTGRES_PASSWORD`, then
   `docker compose up -d --build`. Log in at `http://localhost:8080`, run a `pdf-merge` and an
   `image-convert` and a `media-convert` end-to-end. Then `docker compose --profile ai up -d`
   and `docker compose exec ollama ollama pull qwen3:8b` to test summarize/doc-qa/transcribe.
   Fix whatever reality surfaces (this is where the untested pieces will bite).

4. **Commit** once it runs. Suggested sequence (branch off `master` or keep committing to it —
   confirm with user which branch they want; the repo default `main` doesn't exist yet locally):
   - commit 2: `docs/REPORT.md` + `docs/HANDOFF.md` + `docs/ADDING_TOOLS.md` (docs)
   - commit 3: infra (compose files, .env.example, .gitignore, .dockerignore, README, deploy/)
   - commit 4: server (all of `server/`)
   - commit 5: web (all of `web/`, minus `web/dist/` which should be gitignored)
   End commit messages with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
   Only push/PR when the user asks.

---

## 3. Key decisions already made (don't re-litigate)

- **Stack:** FastAPI + SQLAlchemy 2 + Postgres(pgvector) + Redis + **RQ** workers + React/Vite/
  Tailwind SPA + Docker Compose. Rationale in REPORT §3. RQ was chosen specifically because
  **fork-per-job gives real subprocess kill + timeout + memory isolation** for heavy native
  tools — the load-bearing requirement. Don't swap to Celery/async queues without cause.
- **Integration shapes:** wrap CLI/lib in worker (pikepdf, ffmpeg, gs, pandoc, exiftool,
  ocrmypdf, Pillow, faster-whisper, segno, py7zr) · microservice (Gotenberg for Office/HTML→PDF,
  Ollama for LLM+embeddings, ClamAV) · reverse-proxy whole apps only as optional breadth
  (Stirling-PDF, IT-Tools sharevb fork, Omni-Tools, CyberChef).
- **MVP scope = 17 tools** in SPEC §8 (16 rows + split's burst mode). Phase-2 tools (rembg,
  RapidOCR image→text, ffsubsync, yt-dlp, pdfcpu, pyvips swap), RAG (Docling+pgvector), and the
  audio suite (audio-separator, DeepFilterNet, WhisperX) are deliberately deferred — see
  REPORT §18 roadmap.
- **Local-first:** zero external calls by default. Ollama URL is env-swappable to a cloud
  OpenAI-compatible endpoint as opt-in fallback, never default.
- **Images:** scaffold ships **Pillow** (simple) for `image-convert`; **pyvips is the
  documented perf upgrade**, not shipped. **ImageMagick is deliberately excluded** (CVE surface).
- **Archives:** scaffold ships stdlib+py7zr with guards; **libarchive is the documented upgrade**.

---

## 4. Deviations from SPEC the build agents already made (all reasonable — keep)

- **Infra:** added `caddy_data`/`caddy_config` volumes (ACME cert persistence); added
  compose-only vars `WORKER_MEM_LIMIT=6g` and `SELFX_DOMAIN=localhost` to `.env.example`;
  `SELFX_SECRET_KEY` uses `${SELFX_SECRET_KEY:?err}` (fail-fast) instead of a silent default;
  caddy also publishes 443/udp (HTTP/3).
- **Web:** `User` type has optional `disabled?`/`created_at?` (for Admin page); added
  `src/format.ts` helpers; downloads use authenticated fetch→blob→anchor (so the Bearer token
  is sent) instead of a plain `<a href>`. **This last one matters** — the reviewer should
  confirm the download flow works and the server's `GET /files/{id}/download` accepts the token
  the way api.ts sends it.
- **Server:** added `app/ratelimit.py` (slowapi Limiter + per-user key); added `DEBUG` env var
  (Settings.debug); input files linked to a job via `files.job_id` at creation, reused upload
  → 409; `DELETE /jobs/{id}` on a running job → 409; status codes where SPEC was silent
  (201 creates, 404 unknown tool, 409 conflicts, 400/422 validation).

The frontend was built assuming SPEC's status codes; the server chose specific ones. **The
contract reviewer should check web `api.ts` error handling still lines up with the server's
actual 4xx choices** (esp. 409s the frontend may not expect).

---

## 5. Gotchas / environment notes

- **Windows host, Linux containers.** RQ uses `fork` → the worker only runs in Docker or WSL2,
  not native Windows Python. The API runs natively fine for dev.
- **Python on PATH is 3.14**, code targets 3.12 — fine for `py_compile` parse checks, but real
  runtime is the container.
- Node 24 / npm 11 on PATH; `web` builds cleanly there.
- Docker 29.1.2 is installed and working.
- **Don't trust "it compiles" as "it runs."** The whole server + adapters have never executed.
  The most likely breakages: an adapter using a lib API slightly wrong, a missing entry in
  `requirements.txt`, a CLI flag the installed tool version rejects, or the RQ worker/redis
  wiring. Run it early.
- Research freshness is anchored to **2026-07-07**; model names (Qwen3, Granite 3.3, etc.) and
  "latest" tags should be re-verified on ollama.com/library at install time.
- MCP note (session ambient): several plugin servers need auth via claude.ai connector settings
  or `/mcp`; irrelevant to this build. Agent-Reach (user's global tools) is available if more web
  research is wanted.

---

## 6. Where everything lives

- Repo: `C:\SelfX` (git; branch `master`; only SPEC committed).
- Research digest (human-readable): scratchpad `research_digest.md`; raw: `tasks\w4nrl6dz7.output`.
- Scaffold workflow script (has the exact build+reviewer prompts, resumable):
  `...\848d2b21-...\workflows\scripts\selfx-scaffold-wf_31d6b672-a76.js` (runId `wf_31d6b672-a76`).
- Research workflow script: `...\workflows\scripts\selfhost-suite-research-wf_e40e54df-6f7.js`.
- Report source parts (already concatenated into REPORT.md): scratchpad `report_p1/2/3.md`.

---

## 7. One-paragraph orientation for the next model

The hard thinking is done: the architecture is decided, researched, and written up (SPEC is
the contract, REPORT is the reasoning), and most of the code exists and either builds (web) or
parses (server). Your job is to **finish the 15 tool adapters (SPEC §8), review the whole thing
against SPEC §5/§6/§10, then boot it with `docker compose up` and fix what actually breaks.**
Favor running over reading — the untested surface is where the real bugs are. Keep adapters
small and matching the two reference adapters; the auto-discovery registry means new tools are
one file each with zero other edits. When it runs end-to-end, commit in the layered sequence in
§2.4 and tell the user. Don't expand scope into phase-2 tools until the MVP 17 run clean.
