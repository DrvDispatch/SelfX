# SelfX — Self-Hosted All-in-One Utility Suite
## Technical Guide & Implementation Plan

*Research verified against live GitHub data on 2026-07-07 (a 15-agent research sweep checked
last-commit dates, releases, licenses, and Docker support for ~90 candidate projects).
Companion documents: [SPEC.md](SPEC.md) — the binding technical contract the scaffold
implements; [ADDING_TOOLS.md](ADDING_TOOLS.md) — how to add a new tool.*

---

## 1. Executive summary

**Goal.** A private, self-hosted "Swiss-army-knife" web app replacing dozens of small SaaS
tools: PDF manipulation, document/image/media conversion, OCR, transcription, voice
isolation, metadata removal, archives, QR codes, and local-AI features (summarization,
document Q&A) — modular, so new tools can be added without touching the core.

**Key finding from research: nothing existing covers this whole scope, but every *engine* already exists.**
Stirling-PDF nails PDFs (but only PDFs), ConvertX nails file conversion (but is AGPL and has
no public API), Omni-Tools/IT-Tools nail the utility-dashboard UX (but are 100% client-side
with no backend), Scriberr nails transcription (but only that). The one thing nobody ships is
the **coordinator**: a modular tool registry + job queue + auth + one API across all domains.
That coordinator is deliberately thin (~a few thousand lines), and it is exactly what we build.
Everything heavy — conversion, OCR, inference — is delegated to mature open-source engines
via three integration shapes:

1. **Wrap in the worker** (CLI subprocess or Python library): pikepdf, Ghostscript, FFmpeg,
   Pandoc, ExifTool, OCRmyPDF, Pillow/pyvips, faster-whisper, segno, py7zr.
2. **Call as a Docker microservice**: Gotenberg (LibreOffice/Chromium conversion), Ollama
   (LLM + embeddings), ClamAV (scanning).
3. **Reverse-proxy whole apps** for breadth (optional): Stirling-PDF's full editor UI,
   IT-Tools (sharevb fork), CyberChef, Omni-Tools.

**Recommended stack** (justified in §3): FastAPI + SQLAlchemy + PostgreSQL(+pgvector) +
Redis/RQ workers + React/Vite/Tailwind SPA + Docker Compose, GPU optional. Everything
CPU-viable by default; local-first with zero external calls.

**Status: the scaffold exists.** This repository contains a working implementation of the
MVP architecture — compose stack, backend, worker, 17 tools, dashboard — built against
[SPEC.md](SPEC.md). See README for the quickstart.

---

## 2. Best existing open-source projects to combine

Verdicts below are for *this architecture* (FastAPI + Python worker + Compose). "Verified"
means last activity checked via `gh` on 2026-07-07.

### 2.1 PDF tools

| Project | Verified activity | License | Verdict |
|---|---|---|---|
| **Stirling-PDF** (~86k★) | pushed 2026-07-07, v2.14.0 | Open-core: **MIT core**, proprietary dirs for SSO/teams/audit; free ≤5 users | **Optional reverse-proxy** for its editor UI + 50-tool breadth. Don't build *on* it: it's a 1–2 GB JVM app that internally wraps the same CLIs we wrap directly. Real REST API (`/api/v1/*`, X-API-KEY) if you ever want to call it headlessly. |
| **pikepdf** (~2.8k★) | v10.9.1, 2026-06 | MPL-2.0 | **Wrap (Python lib)** — core of our PDF ops: merge, split, rotate, encrypt/decrypt, repair. qpdf robustness with a Python API. |
| **pypdf** (~10k★) | 6.14.x, 2026-06 | BSD-style | **Wrap** — pure-Python glue: page ops, watermark/stamp, basic text extraction. |
| **qpdf** (~5.2k★) | v12.3.x | Apache-2.0 | Underlies pikepdf; CLI for linearize/repair. No image recompression. |
| **pdfcpu** (~8.7k★) | v0.13.0, 2026-06 | Apache-2.0 | **Wrap (static Go binary)** later for AcroForm fill, N-up/booklet imposition — the gaps pikepdf leaves. |
| **Ghostscript** | 10.x, active | **AGPL-3.0** (dual commercial) | **Wrap CLI, but flag**: the only real PDF *compression* engine (image downsampling via `-dPDFSETTINGS`). AGPL is fine for private self-hosting; a concern only if you offer the service publicly without releasing source. |
| **PyMuPDF** (~10.2k★) | 1.28, 2026-06 | **AGPL-3.0** (dual) | Fastest renderer/extractor, but license-encumbered. Permissive substitute for rendering: **pypdfium2** (Apache/BSD). |
| **pdf2docx** (~3.5k★) | v0.5.13, 2026-05 — **maintenance mode** (Artifex: no active dev) | MIT, **but depends on AGPL PyMuPDF** | **Wrap** for PDF→Word — the only realistic OSS option with layout reconstruction. Accept "good enough, not evolving" + the transitive AGPL flag. |
| **BentoPDF** (~14k★) | active | AGPL-3.0 | Trending client-side (WASM) Stirling alternative — files never leave the browser. No server API ⇒ not a backend building block. |

**Verdict:** wrap the permissive lib/CLI layer (pikepdf + pypdf + Ghostscript, pdfcpu later)
in our worker; Stirling-PDF as an optional proxied app. This beats proxying Stirling for core
ops: tiny per-op footprint vs a JVM, exact API shapes we control, clean licenses.

### 2.2 Document conversion

| Project | Verified activity | License | Verdict |
|---|---|---|---|
| **Gotenberg** (~12.5k★) | v8.34.0, 2026-06 | MIT | **Microservice — the centerpiece.** Stateless REST API wrapping LibreOffice (Office→PDF) + Chromium (HTML/MD/URL→PDF) + pdf engines. Keeps a warm office process (no 1–3 s cold start), handles supervision/timeouts. Key limit: LibreOffice serializes conversions per instance ⇒ scale with replicas, not threads. |
| **unoserver** (~0.9k★) | 2026-06 | MIT | The *right* way to bundle LibreOffice in-worker (persistent daemon, successor to unoconv) — but that costs ~1 GB in every worker image. Only if you refuse an extra service. |
| Raw `soffice --convert-to` | — | MPL-2.0 | **Avoid**: per-call cold start, user-profile lock collisions, zombie processes needing a watchdog. |
| **Pandoc** (~45k★) | 3.10, 2026-06 | GPL-2.0 (fine as subprocess) | **Wrap CLI** (static binary) for markup: MD ↔ HTML ↔ DOCX ↔ EPUB ↔ LaTeX. Not a fidelity Office→PDF tool. |
| **WeasyPrint** (~9.4k★) | v69, 2026-06 | BSD-3 | Browser-free HTML/CSS→PDF (great paged-media support). Add later for templated reports; no JS execution. |
| **Calibre** `ebook-convert` (~25k★) | v9.11, 2026-07 | GPL-3 (subprocess OK) | Definitive ebook conversion; heavy (Qt) ⇒ own sidecar image if/when needed. |
| **Collabora CODE** | active | MPL + branding | Overkill — full collaborative editor; its convert endpoint is the same LibreOffice. |

**Verdict:** Gotenberg as a core microservice + Pandoc in-worker. PDF→Word via pdf2docx (§2.1).

### 2.3 Media conversion & subtitles

| Project | Verified activity | License | Verdict |
|---|---|---|---|
| **FFmpeg** | continuous | LGPL/GPL build-dep | **Wrap the CLI directly** — argv lists (never shell strings), preset system as data, progress via `-progress pipe:1` (machine-readable `out_time_us=` lines vs total duration from `ffprobe`), `-y -nostdin -hide_banner`, per-job timeout+kill. |
| **ConvertX** (~17k★) | v0.18.0, 2026-06 | **AGPL-3.0** | Strongest turnkey converter app (1000+ formats), but: own auth/queue/storage duplicating ours, no stable public API, AGPL. **Reverse-proxy it or skip**; never fork into our backend. |
| **Morphos** | **ARCHIVED 2024** | MIT | Dead — do not build on. (A useful cautionary tale: solo converter apps stall.) |
| **transmute** (~1.1k★) | v2.0.0, 2026-06 | MIT | Young MIT-licensed ConvertX alternative — watchable, and legally absorbable if we ever want its code. |
| **HandBrakeCLI** (~24k★) | 1.11, 2026-06 | GPL-2 | Only if you want its device-preset catalog; ffmpeg covers us. |
| **ffsubsync** (~7.8k★) | 0.5.0, 2026-06 | MIT | **Wrap (pip)** — auto-syncs out-of-sync SRT to audio. Phase-2 subtitle tool. |
| ffmpeg-python / python-ffmpeg wrappers | stale (2024) | — | **Avoid for the hot path** — raw subprocess + `-progress` parsing is more robust. |

### 2.4 Transcription

| Project | Verified activity | License | Verdict |
|---|---|---|---|
| **faster-whisper** (~24k★) | v1.2.1 (2025-10; still the de-facto standard backend) | MIT | **Embed in worker** — CTranslate2, int8 on CPU is ~real-time for small/medium; loads distil-whisper & large-v3-turbo checkpoints. Our default. |
| **whisper.cpp** (~51k★) | v1.9.1, 2026-06 | MIT | The leanest pure-CPU alternative (no torch, quantized GGUF, emits SRT/VTT natively). Swap-in if worker-image weight becomes an issue. |
| **WhisperX** (~23k★) | v3.8.6, 2026-05 | BSD-2 | Word-level timestamps + **speaker diarization** (pyannote, HF-gated token). GPU-leaning; the phase-3 "meeting notes with speakers" path. |
| **Speaches** (ex faster-whisper-server) | v0.9-rc, active | MIT | OpenAI-compatible STT microservice — adopt only if you want a `/v1/audio/transcriptions` network boundary to hot-swap local↔cloud. |
| **NVIDIA Parakeet-TDT 0.6B v3** (ONNX) | NeMo active; weights CC-BY-4.0 | Apache-2.0 code | **The one to watch**: fastest CPU engine measured (~19 s per hour of audio via ONNX), 25 EU languages. Young server wrappers (achetronic/parakeet, sherpa-onnx) — pilot later. |
| Scriberr / Vibe | active | MIT | Finished end-user apps (web / desktop) — competitors/references, not components. |

### 2.5 Voice isolation & noise removal

Two distinct problems, two engines:

| Use case | Pick | Verified | License | Notes |
|---|---|---|---|---|
| **Music stem separation / vocal isolation** | **python-audio-separator** (~1.3k★) | v0.44.2, 2026-05 | MIT | Headless access to the whole UVR model zoo (MDX-Net, VR, Demucs, RoFormer) as lib+CLI+optional REST. CPU-feasible with MDX/Demucs models (tens of sec–few min per song); RoFormer quality tier wants GPU. **Demucs itself is archived** (Meta repo 2024; maintainer fork frozen) — audio-separator wraps its models anyway. UVR GUI is desktop-only, no API. |
| **Speech denoising (recordings/meetings)** | **DeepFilterNet** (~4.4k★) | stable; upstream quiet since 2023 (low-risk: self-contained, few-MB model) | MIT/Apache-2.0 | Faster-than-realtime full-band 48 kHz suppression **on one CPU core**. Pin the version. |
| Quality tier (offline) | ClearerVoice-Studio (MossFormer2) | 2025-08 | Apache-2.0 | Beats DeepFilterNet on PESQ; large transformer ⇒ GPU/long-job tier. |
| Cheap fallback | noisereduce | stable | MIT | Pure-DSP spectral gating; near-instant; stationary noise only. |
| **Ruled out** | facebookresearch/denoiser | **archived** | **CC BY-NC** (non-commercial) | Avoid. |

### 2.6 OCR & document text extraction

Three sub-problems, three answers:

| Sub-problem | Pick | Verified | License | Notes |
|---|---|---|---|---|
| **Searchable PDF** (add text layer) | **OCRmyPDF** (~34k★) | v17.4.1, 2026-07 | MPL-2.0 | The unambiguous standard; wraps Tesseract+Ghostscript+qpdf; deterministic CLI; pure CPU. `--skip-text` tolerates mixed docs. |
| **Image → text** | **RapidOCR** (~7k★) on CPU; PaddleOCR v3 (~85k★) when you want PP-Structure | v3.9.1, 2026-07 | Apache-2.0 | RapidOCR = PaddleOCR's PP-OCRv5 models on ONNX **without the PaddlePaddle dependency** — the light CPU path. EasyOCR is slipping (no release since 2024) — fallback only. |
| **PDF → clean Markdown (RAG ingestion)** | **Docling** (~63k★, IBM/LF AI) | v2.110.0, 2026-07 | MIT | Layout/tables/reading-order aware, CPU-tolerant, LangChain/LlamaIndex integrations, optional `docling-serve` REST. |
| Quality/GPU tier | MinerU (~74k★) | 2026-07 | Apache-2.0 **+ extra commercial terms** (ex-AGPL) | Highest fidelity on hard/scientific PDFs; read LICENSE.md first. |
| Flagged | Surya / marker | active | Apache/GPL-3 code + **revenue-capped weights** | SOTA quality but license-awkward for a product; GPU-leaning. olmOCR: 7B VLM, GPU-mandatory. |

### 2.7 Local AI: serving, RAG, models

| Component | Pick | Verified | License | Verdict |
|---|---|---|---|---|
| **LLM serving** | **Ollama** (~176k★) | pushed 2026-07-07 | MIT | One container = chat + embeddings behind an OpenAI-compatible API; model pulls one command. llama.cpp `llama-server` (MIT) if you want raw control; **vLLM only when a GPU + high concurrency arrive** (CPU backend experimental). LM Studio: closed-source core, not compose-native — no. |
| **Vector store** | **pgvector** (~22k★) | 2026-07 | PostgreSQL | RAG = one more table in the Postgres we already run; HNSW handles millions of chunks on CPU. Qdrant (Apache-2.0) only when you outgrow it; Chroma for prototypes; sqlite-vec for zero-infra edge. |
| **RAG glue** | **Build directly** (~200 lines), optionally with LlamaIndex or Haystack primitives (both permissive) | — | MIT/Apache | Chunk → embed → pgvector → top-k → stuffed prompt → Ollama. LangChain is more than this needs. |
| **Doc-chat app (optional UI)** | **AnythingLLM** (~63k★, MIT) over Open WebUI | 2026-07 | MIT vs **"Open WebUI License"** (non-OSI branding clause >50 users, post-v0.6.6) | AnythingLLM has a real REST API + clean license. Dify: powerful but heavyweight platform + license restrictions (no multi-tenant resale, logo clause). Flowise: Apache-2.0 community edition, open-core. |
| **Models (mid-2026, CPU/modest GPU)** | **Qwen3 8B / 4B** (Q4_K_M) workhorse; IBM Granite 3.3 8B (Apache-2.0) strong at summarization/RAG grounding; Gemma 3 4B/12B; Qwen3 30B-A3B MoE (≈3B active) if RAM-rich CPU box; Phi-4 14B on GPU | — | — | Embeddings: **nomic-embed-text** (fast) or **bge-m3** (multilingual, 8k ctx) via Ollama. |

### 2.8 Image tools

| Task | Pick | Verified | License | Verdict |
|---|---|---|---|---|
| **Convert/resize/compress** | **libvips/pyvips** primary; **Pillow (+pillow-heif)** fallback | both pushed 2026-07 | LGPL-2.1 lib / HPND | pyvips: 4–8× faster than ImageMagick/Pillow, flat memory (streaming), small CVE surface. Pillow: zero-friction wheels, ubiquitous. *(Scaffold ships Pillow first for simplicity; pyvips is the documented perf upgrade.)* |
| **ImageMagick** | **Deliberately excluded from default path** | 7.1.2, active | permissive | Ongoing CVE record (2025: CVE-2025-55298 format-string RCE, CVE-2025-68618 SVG DoS, policy bypasses with Ghostscript linked). If ever added: pin, harden policy.xml, no Ghostscript delegate, sandbox. |
| **Background removal** | **rembg** (~23.6k★) | v2.0.76, 2026-06 | MIT | CPU-viable (u2netp/isnet ~1–3 s/image); prefer **BiRefNet** session (MIT weights — cleanest) for quality. Watch per-model weight licenses (some u2net weights research-only). |
| **Upscaling** | **spandrel** (MIT, chaiNNer's engine) loading Real-ESRGAN weights on CPU (async jobs); Vulkan GPU + upscayl-ncnn (**AGPL**) for speed | Real-ESRGAN repo itself stale | BSD-3 weights | ncnn/Vulkan builds are effectively GPU-only; PyTorch-on-CPU is minutes-per-image but fine as a queued job. |
| **Captioning** | Ollama vision models: **moondream2** (~2B, seconds on CPU), qwen2.5-VL/llava for quality | active | Apache-2.0 | BLIP is archived — superseded. |
| **Generation (optional, GPU)** | ComfyUI (~120k★, GPL-3, real API) or SD.Next (Apache-2.0, A1111-compatible API) | 2026-07 | — | Fooocus effectively frozen (no release since 2024-08). CPU generation impractical — GPU phase only. |

### 2.9 Misc utilities, archives, metadata, scanning

| Task | Pick | Verified | License | Verdict |
|---|---|---|---|---|
| **Browser-style dev utilities** | **Reverse-proxy, never rebuild**: IT-Tools **sharevb fork** (active line: v2026.1.4; upstream releases frozen since 2024-10) + **Omni-Tools** (MIT) + **CyberChef** (Apache-2.0, GCHQ) | 2026-07 | GPL-3/MIT/Apache | All three are 100% client-side static SPAs — a nginx container each; rebuilding ~400 tools is wasted effort. Pin image tags (supply-chain). DevToys = desktop app, ruled out. |
| **Metadata** | **ExifTool** | 2026-05, frequent releases | Artistic/GPL | **Wrap CLI**; `-all=` strip on a copy. PyExifTool `-stay_open` avoids Perl startup per call. No serious competitor. |
| **Archives (untrusted)** | **libarchive** via python-libarchive-c (primary target); py7zr for .7z; stream-unzip for constant-memory ZIP | libarchive v3.8.8, 2026-06; py7zr v1.1.3 security release 2026-06 | BSD / LGPL / MIT | Safety comes from *our wrapper*: cap total size, entry count, ratio (bomb defense), reject traversal/symlinks, extract to fresh dir, cgroup limits. **patool ruled out for untrusted input** (delegates to external binaries you can't bound). *(Scaffold ships stdlib+py7zr with all guards; libarchive is the documented upgrade.)* |
| **QR** | **segno** | 1.6.6, feature-complete | BSD-3 | Zero-dependency, faster than python-qrcode, SVG/PNG out. |
| **Virus scan (optional)** | **ClamAV** (clamd) | 1.5.3, 2026-07 | GPL-2 (standalone service) | Own container; worker streams bytes via INSTREAM. Budget ~1.5–2 GB RAM for signatures. |
| **File-type sniffing** | **python-magic** (libmagic) authoritative; puremagic pure-python fallback; **Magika** (Google, Apache-2.0, ONNX ~ms on CPU) as optional second opinion on text/code formats | libmagic upstream 2026-07 | MIT/BSD | Wrapper PyPI cadence is slow but the value lives in the OS `libmagic1` package — keep *that* patched. filetype.py effectively stale (2022) — skip. |
| **Media download (optional tool)** | **yt-dlp** (~176k★, Unlicense) embedded as Python lib (+ gallery-dl GPL-2 for image hosts) | release 2026-07-04 | public domain | Everything else (cobalt — AGPL, quiet since 2026-04; MeTube — AGPL GUI) wraps yt-dlp anyway. Must auto-update or extractors rot. ToS risk is the user's; keep it a private, user-responsibility feature. |

### 2.10 Cross-cutting infrastructure (from the gap-fill round)

| Layer | Pick | Runner-up | Why |
|---|---|---|---|
| **Job queue** | **RQ** (BSD, v2.10 2026-06) | Procrastinate (MIT, Postgres LISTEN/NOTIFY — if "no Redis" is a hard rule); Celery only if you need canvas/beat/Flower | The load-bearing requirement is **cancellation that actually kills a child subprocess** + hard timeouts + memory isolation for leaky native tools. RQ's fork-per-job work-horse gives that nearly free: `job_timeout` SIGKILLs runaways; `send_stop_job_command` kills on demand; each ffmpeg/LibreOffice run gets its own address space reclaimed on exit. Launch subprocesses with `start_new_session=True` and kill the process group. Redis doubles as progress pub/sub bus. Dramatiq (LGPL + thread workers), arq/Taskiq (async in-process), Huey, PgQueuer (young) all rank below for this specific workload. |
| **Artifact storage** | Local named volume; temp-then-atomic-move; DB-tracked `expires_at`; scheduled cleanup | S3-compatible **only at multi-node**: then SeaweedFS/Garage (Apache-2.0) — **MinIO is AGPL now** | Single-node object storage is pure overhead. |
| **Gateway/SSO (advanced, multi-app phase)** | **Traefik v3 + Authelia** (+ lldap for GUI user management) | Authentik (all-in-one w/ admin GUI, ~10× RAM, open-core); Caddy if you prefer one Caddyfile | Solves "N proxied apps, N auth systems": one login portal, SSO cookie across subdomains, headers injected into auth-less apps (CyberChef etc.), OIDC provider, and since v4.39 bearer-token auth for headless API clients. ~150 MB RAM total vs Keycloak's 1.25 GB+ JVM. |

### 2.11 Should we fork something instead? (prior-art verdict)

No. The four nearest misses each cover one axis and miss the rest: Stirling-PDF (PDF-only,
JVM, open-core), ConvertX (conversion-only, AGPL, no public API), Omni-Tools/IT-Tools
(client-side, no backend/queue/auth), Homarr/Homepage (portals, zero processing),
Morphos (archived). Two projects are worth *reading* for architecture: Stirling-PDF's
service-layer-orchestrating-CLIs + Pipelines engine, and **Activepieces** (~23k★, MIT core) —
a production-grade "plugin registry + worker queue + API" in TypeScript that is the best
existing reference for exactly the coordinator we're building. Build the thin coordinator;
compose the engines.

---

## 3. Recommended architecture

```
                        ┌──────────────────────────────────────────────┐
                        │                 Docker network                │
 Browser ──HTTP──▶ web (nginx)                                          │
                   │  serves React SPA                                  │
                   │  proxies /api/ ──▶ api (FastAPI) ──▶ db (Postgres+pgvector)
                   │                      │        └────▶ redis (queue + progress)
                   │                      │ enqueue
                   │                      ▼
                   │                 worker (RQ, same image as api)
                   │                   │  subprocess: ffmpeg, gs, ocrmypdf,
                   │                   │  pandoc, exiftool · libs: pikepdf,
                   │                   │  Pillow, faster-whisper, segno, py7zr
                   │                   ├──HTTP──▶ gotenberg (LibreOffice/Chromium)
                   │                   ├──HTTP──▶ ollama   (LLM+embeddings, profile: ai)
                   │                   └──TCP───▶ clamav   (scan, profile: security)
                   │
                   ├─(profile: extras)─▶ stirling-pdf (proxied full PDF editor)
                   └─(profile: proxy)──▶ caddy (VPS TLS termination)

 Shared volume /data: uploads/ · outputs/<job_id>/ · tmp/<job_id>/
```

**Why this stack (and not the alternatives):**

- **Backend: FastAPI (Python)** — not Node. The deciding factor is that the tool ecosystem
  is Python-native: pikepdf, OCRmyPDF, faster-whisper, rembg, audio-separator, pdf2docx,
  Docling are all Python libraries. A Node backend would shell out to Python constantly.
  FastAPI gives typed request/response models (Pydantic), OpenAPI docs for free, and a huge
  hiring/maintenance pool.
- **Queue: Redis + RQ** — not Celery, not Postgres-based. Justification in §2.10: fork-per-job
  isolation is precisely what heavyweight native subprocesses need, at a fraction of Celery's
  operational surface. Redis additionally serves as the progress bus and rate-limit store.
  If you later hate Redis, Procrastinate is the documented Postgres-native alternative.
- **DB: PostgreSQL (pgvector image)** — not SQLite. Two containers (api + worker) writing
  concurrently is where SQLite gets painful, and pgvector gives the RAG phase a vector store
  for free. SQLite remains fine for laptop-scale single-process experiments; SQLAlchemy keeps
  both possible.
- **Frontend: React + Vite + TypeScript + Tailwind (SPA)** — not Next.js. An authenticated
  dashboard behind a login has zero need for SSR/SEO; Next.js would add a Node server,
  hydration complexity, and framework churn for no benefit. A static SPA behind nginx is one
  order of magnitude simpler to build, ship, and reason about. (If you later want a public
  marketing site, that can be Next.js separately.)
- **Compose, not Kubernetes** — a single VPS runs this comfortably; K8s is an advanced-section
  concern (§20). Profiles (`ai`, `extras`, `security`, `proxy`) keep optional weight off by default.
- **One server image for api + worker** — same code, same deps, different command. Eliminates
  drift between the API's view of tools and the worker's.

## 4. Tool categories and implementation method

| Category | Method | Engine(s) | Why this shape |
|---|---|---|---|
| PDF merge/split/rotate/encrypt | **Python lib in worker** | pikepdf | In-process, ms-fast, no service overhead |
| PDF compress | **Wrap CLI** | Ghostscript | Only real compression engine; isolate as one adapter (AGPL-flagged) |
| PDF → Word | **Python lib** | pdf2docx | Only OSS layout-reconstructing option |
| PDF forms / imposition (later) | **Wrap CLI** | pdfcpu | Static Go binary, cleanest CLI contract |
| Office/HTML/MD → PDF | **Microservice** | Gotenberg | Keeps 1 GB LibreOffice+Chromium out of worker image; warm process; scale by replicas |
| Markup conversion | **Wrap CLI** | Pandoc | Tiny static binary; deterministic |
| Ebook conversion (later) | **Wrap CLI, sidecar image** | Calibre | Heavy Qt dep — quarantine it |
| Image convert/resize | **Python lib** | Pillow(+heif) now, pyvips upgrade | In-process; pyvips when throughput matters |
| Background removal (later) | **Python lib** | rembg (BiRefNet session) | CPU-viable ONNX |
| Upscaling (later) | **Python lib / GPU tier** | spandrel + Real-ESRGAN weights | Async job absorbs CPU slowness |
| Media conversion | **Wrap CLI** | FFmpeg | Full control: presets-as-data, progress, kill |
| Subtitle extract/convert | **Wrap CLI** | FFmpeg (+ffsubsync later) | Same adapter family |
| Transcription | **Python lib** | faster-whisper | De-facto standard; no extra service |
| Diarized meeting notes (later) | **Python lib / GPU tier** | WhisperX or pyannote+faster-whisper | HF-gated models; slow on CPU |
| Voice isolation (later) | **Python lib** | python-audio-separator | UVR model zoo, headless |
| Speech denoise (later) | **Python lib** | DeepFilterNet | Realtime on one CPU core |
| OCR (searchable PDF) | **Wrap CLI** | OCRmyPDF | Deterministic, battle-tested |
| Image → text (later) | **Python lib** | RapidOCR | ONNX CPU, no PaddlePaddle |
| PDF → Markdown for RAG (later) | **Python lib / microservice** | Docling | MIT, CPU-tolerant |
| Metadata removal | **Wrap CLI** | ExifTool | Unmatched format breadth |
| Archives | **Python lib + guards** | zipfile/py7zr now, libarchive upgrade | Guards are ours regardless of lib |
| QR / generators | **Build directly** | segno | Trivial |
| AI summarize / doc-Q&A | **Microservice API** | Ollama | Swappable OpenAI-shaped boundary |
| RAG multi-doc chat (later) | **Build directly** | pgvector + Ollama | ~200 lines we control |
| Dev browser utilities | **Reverse-proxy apps** | IT-Tools(sharevb)/Omni-Tools/CyberChef | Client-side SPAs; rebuilding is waste |
| Full PDF editor UI | **Reverse-proxy app** | Stirling-PDF | Breadth for free, isolated |
| Virus scan | **Microservice** | ClamAV | GPL isolation + RAM footprint containment |
| Media download (optional) | **Python lib** | yt-dlp (+gallery-dl) | Everything else wraps it anyway |

## 5. AI tools plan

All AI is **local-first**: default deployment makes zero external calls. The Ollama URL is an
env var — pointing it at any OpenAI-compatible endpoint (including a cloud one) is a
one-line opt-in fallback, never the default.

**Phase A — shipped in scaffold:**
1. **Summarization** (`ai-summarize`): extract text (pypdf/python-docx/raw) → chunk to fit
   context → `POST /api/chat` to Ollama (default model `qwen3:8b`, env-set) → styled summary
   (short/medium/detailed). Tools self-report `available:false` with a reason when Ollama is
   down, so the UI degrades gracefully.
2. **Single-doc Q&A** (`doc-qa`): same extraction, question stuffed with up to ~24k chars of
   document — no vector store needed for one document that fits context. This covers 80% of
   "chat with my PDF" value at 5% of RAG's complexity.
3. **Transcription** (`transcribe`): faster-whisper, model size env-tunable
   (tiny/base/small/medium), txt/srt/vtt/json outputs.

**Phase B — RAG (multi-doc, persistent):**
- Ingestion job: Docling (PDF/DOCX → structured markdown) → chunk (~800 tokens, overlap) →
  embeddings via Ollama (`nomic-embed-text` or `bge-m3`) → pgvector table
  (`documents`, `chunks(embedding vector(768))`, HNSW index).
- Query: embed question → top-k cosine + Postgres full-text hybrid → stuffed prompt with
  citations → Ollama. Build directly (optionally on LlamaIndex/Haystack primitives);
  skip LangChain-scale abstraction.
- OCR fallback in ingestion: scanned PDFs routed through OCRmyPDF first.

**Phase C — audio intelligence:**
- Meeting summarization: transcribe → (optional) diarize (WhisperX/pyannote; HF token,
  GPU-preferred) → LLM summary with speaker attribution + action items.
- Voice isolation (`audio-separator`) and speech denoise (DeepFilterNet) as standalone tools.

**Phase D — vision (optional):**
- Image captioning via Ollama vision models (moondream2 on CPU; qwen2.5-VL on GPU).
- Image generation only with GPU: ComfyUI (proxied, has an API) or SD.Next (Apache-2.0).

**Model guidance (mid-2026):** Qwen3 8B Q4_K_M default; Qwen3 4B on small VPSes; Granite 3.3
8B for grounded RAG answers; Qwen3 30B-A3B MoE on RAM-rich CPU boxes (near-14B quality at
~3B-active speed). Always verify availability on ollama.com/library at install time.

## 6. Docker Compose layout

Core (always on): `web` (nginx, **the only published port**, 8080) · `api` · `worker` ·
`db` (pgvector/pgvector:pg16) · `redis` (7-alpine) · `gotenberg` (gotenberg:8).
Profiles: `ai` → ollama · `extras` → stirling-pdf (:8081) · `security` → clamav ·
`proxy` → caddy (80/443, VPS TLS). `docker-compose.gpu.yml` overlays NVIDIA device
reservations onto worker + ollama and flips whisper to cuda/float16.
All services `restart: unless-stopped`, non-root where we control the image,
`no-new-privileges`, healthchecks on db/redis/api; api waits for healthy db+redis.
Full service table with ports/volumes in [SPEC.md §2](SPEC.md).

## 7. Folder structure

See [SPEC.md §1](SPEC.md) for the annotated tree. Shape: `server/` (one Python package,
`app/`, serving both API and worker), `web/` (Vite SPA), `deploy/` (Caddyfile, VPS notes),
`docs/`, compose files at root. Tool adapters live one-per-file in `server/app/tools/` and
are **auto-discovered** — adding a tool touches zero existing files.

## 8. Backend API design

REST under `/api/v1`, JWT bearer auth, exact shapes in [SPEC.md §5](SPEC.md). Design choices
worth calling out:

- **Uploads are separate from jobs** (`POST /files` → ids, then `POST /jobs {tool, file_ids,
  params}`): enables multi-file tools (merge), file reuse across jobs, and streaming size
  enforcement in one place.
- **`GET /tools` is generated from the registry** — the frontend renders tool pages purely
  from metadata (`accepts`, `min_files`, JSON-Schema `params_schema`, `available` +
  `unavailable_reason`). New adapter ⇒ new UI card, no frontend change.
- **Job status is polled** (2 s while active). Polling is deliberately chosen over
  SSE/WebSockets for the MVP: with fork-per-job workers and a DB-backed progress column it is
  the simplest correct thing; an SSE endpoint reading Redis pub/sub is a documented later
  upgrade that changes no data model.
- Params are validated twice: rendered client-side from JSON Schema, re-validated server-side
  with `jsonschema` before enqueue.

## 9. Frontend dashboard design

Five pages (login, dashboard, tool page, jobs, admin), dark dense Tailwind UI, no component
library, no state library. The interesting piece is the **schema-driven ParamsForm**: it maps
JSON-Schema types → inputs (enum→select, boolean→checkbox, number→bounded input,
`format:"multiline"`→textarea), so tools define their UI declaratively. Tool cards grey out
with a tooltip when a dependency is down (Ollama off), rather than disappearing —
discoverability without broken flows. Jobs page shows live progress bars and per-output
download buttons, and stops polling when nothing is active.

## 10. Worker / job queue design

- Two RQ queues: `default` (fast: PDF ops, images, QR) and `heavy` (media, OCR, AI). One
  worker container consumes both (`default` first); scale by `docker compose up -d --scale
  worker=3`, or dedicate a GPU worker to `heavy` later.
- Job lifecycle: `queued → running → done|error|canceled`, timestamps + progress (0..1) +
  human `message` on the jobs row; worker is the only writer after enqueue.
- Every job runs in a fork-per-job work-horse (RQ) with `JOB_TIMEOUT_SECONDS` hard kill.
  Subprocesses are spawned with list-argv, `shell=False`, own session — cancel/timeout kills
  the whole process group, so no orphaned ffmpeg.
- Outputs written to `/data/tmp/<job_id>/` scratch, results placed in
  `/data/outputs/<job_id>/`, scratch wiped in `finally`; every result file is registered with
  an `expires_at`.
- Failures store a user-safe message; full traceback goes to logs only.

## 11. Database schema

Three tables now — `users`, `jobs`, `files` — exact columns in [SPEC.md §4](SPEC.md);
`documents`/`chunks(embedding vector)` arrive with RAG (Phase B). Files carry
`kind` (upload|output), `job_id` linkage, and `expires_at` for retention. Jobs carry `params`
JSONB and `rq_job_id` so the queue and the record can always be reconciled. UUIDs everywhere;
`create_all` on startup now, Alembic once the schema starts moving.

## 12. File storage strategy

Local named volume, `/data`, three zones: `uploads/<file_uuid>` (originals, uuid-named —
client filenames never touch the filesystem), `outputs/<job_id>/` (results, original-style
names for pleasant downloads), `tmp/<job_id>/` (scratch, wiped per job). Temp-then-move keeps
half-written files unservable. Retention: hourly task deletes expired rows+files and orphaned
scratch dirs; `FILE_RETENTION_HOURS` env (default 24, 0 = keep). S3-compatible storage is a
deliberate non-goal until workers span hosts — then SeaweedFS or Garage (Apache-2.0), **not
MinIO (AGPL)**.

## 13. Security model

Threat model: untrusted files from semi-trusted users, on a box you own.

1. **Ingress**: single published port (web); Caddy TLS on VPS; api/db/redis/gotenberg
   unreachable from outside the Docker network.
2. **AuthN/Z**: bcrypt + JWT (secret must be set — startup refuses default secret outside
   debug); per-object ownership checks on downloads/jobs; admin role separated; rate limits
   (slowapi) on upload + job creation.
3. **Upload gate** (order matters): stream-to-disk with hard byte cap enforced mid-stream
   (never trust Content-Length) → uuid server-side filename, sanitized display name →
   **content sniff with python-magic** and extension/allowlist check per tool → optional
   ClamAV INSTREAM scan → only then enqueue-able. Content decides routing, never extension alone.
4. **Execution**: all subprocess calls are argv lists (`shell=False`), timeouts, cwd confined
   to the job scratch dir; user params reach argv only as validated enums/numbers or file
   paths (leading-dash-safe). No ImageMagick in the image. Ghostscript present but only
   reachable through the pdf-compress adapter with fixed flags.
5. **Archive guards**: path-traversal prefix check on resolved paths, entry-count cap (10k),
   expanded-size cap (2 GiB), compression-ratio ceiling (100×), symlinks rejected.
6. **Containers**: non-root users, `no-new-privileges`, memory limit on worker, healthchecks;
   optional per-tool hardening later (seccomp, read-only rootfs, `network_mode: none` for a
   dedicated extraction worker).
7. **Data hygiene**: auto-deletion by retention; error messages never leak paths/tracebacks;
   logs stay server-side; original filenames sanitized (separators, NUL, length).
8. **Supply chain**: pinned image tags for proxied third-party SPAs; pinned Python deps;
   `libmagic1`/ClamAV/ExifTool patched via scheduled image rebuilds (monthly cron rebuild is
   the single most effective habit — several engines here parse hostile input in C).

---

## 14. Hardware requirements

| Tier | Specs | What runs well |
|---|---|---|
| **Minimum (core, no AI)** | 2 vCPU, 4 GB RAM, 40 GB SSD | PDF ops, image/document conversion, metadata, archives, QR. Gotenberg is the biggest resident (~0.5–1 GB). |
| **Recommended (full CPU suite)** | 4–8 vCPU, 16 GB RAM, 100+ GB NVMe | Adds ffmpeg transcodes, OCR, whisper-small transcription, Ollama with a 4–8B Q4 model (≈5–6 GB RAM resident), ClamAV (+2 GB) if enabled. |
| **Comfortable (AI-heavy CPU)** | 8+ vCPU, 32 GB RAM | Qwen3 30B-A3B MoE, parallel heavy jobs, Stirling + utility SPAs proxied alongside. |
| **GPU tier (optional)** | + NVIDIA 8–24 GB VRAM (RTX 3060 12 GB is the sweet spot entry) | Fast whisper-large, WhisperX diarization, RoFormer stem separation, upscaling, image generation, 14B+ models at interactive speed. |

Disk is dominated by models (whisper-small ~0.5 GB, an 8B Q4 LLM ~5 GB, UVR/rembg models
0.1–1 GB each) and `/data` retention. Budget 20 GB for models alone on the full suite.

## 15. GPU vs CPU recommendations

**Default to CPU; add GPU for four specific reasons.** Everything in the MVP is CPU-sized by
deliberate choice: faster-whisper int8 (small/medium ≈ realtime), Ollama 4–8B Q4 (seconds-per-
job batch latency, fine for queued work), OCRmyPDF/Tesseract (CPU-native), ffmpeg x264/x265.
A GPU changes the calculus only for: (1) whisper-large / diarization at volume, (2) interactive-
speed LLM chat or >14B models, (3) RoFormer-class stem separation & speech enhancement,
(4) upscaling/image generation (effectively GPU-mandatory). The stack is pre-wired for this:
`docker-compose.gpu.yml` flips worker+Ollama to CUDA without touching code, and the OpenAI-
shaped Ollama boundary means a later vLLM swap is config, not surgery. Avoid buying GPU
up-front for a personal instance — measure CPU queue latency first.

## 16. Local development setup

```bash
cp .env.example .env               # set SELFX_SECRET_KEY + admin password
docker compose up -d --build       # full stack at http://localhost:8080
# hot-reload development:
docker compose up -d db redis gotenberg
cd server && pip install -r requirements.txt && uvicorn app.main:app --reload  # api :8000
python -m app.worker               # worker (Linux/WSL2; RQ forks — on Windows use Docker)
cd web && npm install && npm run dev   # Vite dev server :5173, /api proxied to :8000
```
Windows note: develop the worker under WSL2 or Docker (RQ uses `fork`). The API runs
natively fine.

## 17. Production VPS setup

1. VPS (§14 sizing), Docker + compose plugin, non-root deploy user.
2. DNS A record → VPS; `SELFX_DOMAIN=tools.example.com` in `.env`.
3. Harden `.env`: long random `SELFX_SECRET_KEY`, strong `SELFX_ADMIN_PASSWORD`, strong
   `POSTGRES_PASSWORD`, set `FILE_RETENTION_HOURS`, `MAX_UPLOAD_MB` to taste.
4. `docker compose --profile proxy --profile ai up -d --build` — Caddy terminates TLS
   (auto-Let's Encrypt) and proxies to web; only 80/443 exposed. Firewall (ufw): allow
   22/80/443 only.
5. `docker compose exec ollama ollama pull qwen3:8b && docker compose exec ollama ollama pull nomic-embed-text`
6. Backups: nightly `pg_dump` + `/data` outputs if retention is long; models are re-pullable.
7. Updates: monthly `docker compose pull && docker compose up -d --build` (see §13.8).
8. Multi-app phase: when you proxy Stirling/IT-Tools/CyberChef publicly, front everything
   with Traefik+Authelia (§2.10) for one SSO portal instead of N logins.

## 18. Step-by-step build roadmap

| Step | Deliverable | Status |
|---|---|---|
| 0 | Research + this report + SPEC contract | ✅ done |
| 1 | Compose skeleton: db, redis, api healthz, web hello | ✅ scaffolded |
| 2 | Auth (bootstrap admin, JWT), users table | ✅ scaffolded |
| 3 | Upload → job → worker → download loop with one tool (pdf-merge) | ✅ scaffolded |
| 4 | Tool registry + auto-discovery + schema-driven UI forms | ✅ scaffolded |
| 5 | MVP tool set (17 tools, §19) + jobs page + admin | ✅ scaffolded |
| 6 | **You are here**: build images, run, pull models, kick tires; fix what reality finds | next |
| 7 | Retention/cleanup validation, backups, VPS deploy with TLS | week 1–2 |
| 8 | Phase-2 tools: rembg, RapidOCR image→text, ffsubsync, yt-dlp, pdfcpu forms; pyvips swap | week 2–4 |
| 9 | RAG: Docling ingestion + pgvector + doc-chat UI (Phase B, §5) | month 2 |
| 10 | Audio suite: audio-separator, DeepFilterNet, WhisperX meeting notes | month 2–3 |
| 11 | Proxied apps (Stirling, IT-Tools, CyberChef) + Traefik/Authelia SSO | month 3 |
| 12 | GPU overlay in anger; SSE progress; API tokens for headless use | as needed |

## 19. MVP version (what the scaffold implements)

Flow: login → pick tool → drag files → params form → job queued → worker processes →
progress → download → history in dashboard. Seventeen tools across six categories:

- **PDF**: merge, split (ranges or burst-to-zip), compress (gs quality presets), PDF→Word
- **Documents**: Office/HTML/MD→PDF (Gotenberg), markup convert (Pandoc)
- **Images**: convert/resize/quality/strip-metadata (Pillow+HEIC)
- **Media**: ffmpeg presets (mp4-h264, webm-vp9, mp3, opus, wav, flac, gif) with live progress
- **Utilities**: metadata removal (ExifTool), archive compress (zip/7z), archive extract
  (guarded), QR generator (param-only tool — proves the zero-file tool path)
- **AI**: transcribe (faster-whisper, txt/srt/vtt/json), summarize (Ollama), single-doc Q&A
  (Ollama) — all degrade gracefully to "unavailable" when the `ai` profile is off
- Plus: job history w/ cancel/delete, retention cleanup, admin (users, stats, queue depth),
  rate limiting, upload validation.

## 20. Advanced version

Everything in roadmap steps 8–12, plus, when genuinely needed: multi-node workers with an
Apache-licensed S3 store (SeaweedFS/Garage); SSE job streams; per-tool sandboxed worker pools
(`network_mode: none` for extraction, seccomp profiles); Authelia bearer-token API access;
webhook notifications; workflow chaining (Stirling-Pipelines-style: OCR→compress→watermark as
one job graph — the registry's `run(ctx)` contract already composes); Kubernetes only if you
outgrow one box — the images are already 12-factor (env-config, stateless api, queue-driven
workers), so a Helm chart is translation, not redesign.

## 21. Final recommended stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + Vite + TypeScript + Tailwind (SPA, nginx) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2 |
| Queue | Redis 7 + RQ (queues: default, heavy) |
| DB | PostgreSQL 16 + pgvector |
| Doc conversion | Gotenberg 8 (microservice) + Pandoc (CLI) |
| PDF | pikepdf/pypdf (lib) + Ghostscript (CLI, flagged) + pdf2docx |
| Media | FFmpeg (CLI, presets-as-data) |
| OCR | OCRmyPDF/Tesseract → RapidOCR → Docling (phased) |
| STT | faster-whisper (embedded) |
| Audio cleanup | python-audio-separator + DeepFilterNet (phase 2) |
| Images | Pillow+pillow-heif → pyvips; rembg; spandrel |
| AI | Ollama (qwen3:8b default) + pgvector RAG, OpenAI-shaped boundary |
| Misc | ExifTool, segno, py7zr→libarchive, python-magic, ClamAV (opt) |
| Proxied apps (opt) | Stirling-PDF, IT-Tools (sharevb), Omni-Tools, CyberChef |
| Deploy | Docker Compose + profiles; Caddy TLS; GPU overlay file |
| Gateway/SSO (multi-app) | Traefik v3 + Authelia (+ lldap) |

## 22. Concrete next steps

1. `cp .env.example .env`, set the three secrets, `docker compose up -d --build`, log in at
   `http://localhost:8080`, run a pdf-merge and an ffmpeg job end-to-end.
2. `docker compose --profile ai up -d && docker compose exec ollama ollama pull qwen3:8b` —
   then test summarize/doc-qa/transcribe.
3. First real-world friction pass: upload your actual files; tune `MAX_UPLOAD_MB`,
   whisper model size, worker memory limit.
4. Deploy to the VPS per §17; add the `proxy` profile.
5. Pick the first phase-2 tool you actually miss (likely rembg or image→text OCR) and add it
   via [ADDING_TOOLS.md](ADDING_TOOLS.md) — the adapter pattern makes this a one-file change;
   that experience will validate the plugin model better than any document.

---

### Appendix: license flags collected in one place

| Severity | Component | Flag |
|---|---|---|
| Note | Ghostscript, PyMuPDF (via pdf2docx) | AGPL/dual-commercial — fine for private self-host; revisit before offering as a public multi-tenant service |
| Note | ConvertX, MeTube, cobalt, tinyauth, upscayl-ncnn, BentoPDF | AGPL — run unmodified as separate containers only; never vendor code |
| Note | MinIO | Now AGPL — prefer SeaweedFS/Garage if S3 is ever needed |
| Note | Open WebUI | Custom non-OSI license since v0.6.6 (branding clause >50 users) — AnythingLLM (MIT) preferred |
| Note | Dify | No multi-tenant resale, logo retention clause |
| Note | Stirling-PDF, Flowise, Authentik, Activepieces | Open-core — verify the feature you use is in the FOSS core |
| Note | Surya / marker | Model weights carry revenue-cap commercial terms; marker code is GPL-3 |
| Note | MinerU | Apache-2.0 **plus** extra commercial/deployment terms (ex-AGPL) |
| Avoid | facebookresearch/denoiser | CC BY-NC (non-commercial) + archived |
| OK as subprocess | Pandoc (GPL-2), Calibre (GPL-3), ExifTool, ClamAV (GPL-2), gallery-dl (GPL-2), IT-Tools (GPL-3) | Copyleft doesn't attach across a process boundary; don't vendor their code |
| Watch checkpoints | rembg (some u2net weights), UVR/RoFormer checkpoints, Moonshine weights, pyannote HF-gated pipelines | Model weights can carry stricter terms than the wrapping MIT code — audit the specific checkpoints you ship |
