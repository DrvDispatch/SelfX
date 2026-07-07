# SelfX — Knowledge Base (chat-with-docs) + Natural-Language Agent — Build Plan

_From a 5-agent GitHub/web research sweep (verified live 2026-07-07). Companion to
[REPORT.md](REPORT.md) and [AUDIT.md](AUDIT.md)._

## Verdict

Both headline features are **built natively on SelfX's existing stack** (Postgres+**pgvector**,
Ollama on the RTX 3080 Ti, RQ worker, the JSON-Schema tool registry, Docling, `_text_extract`).
The research confirmed SelfX is ~90% there and that embedding a separate app would *duplicate*
infra (its own auth, user model, vector store) and fragment where documents live.

- **Chat-with-your-documents:** BUILD native persistent RAG on pgvector + Ollama. `multi_doc_qa.py`
  is already the exact chunk→embed→retrieve→answer loop, only ephemeral (in-memory numpy). Delta to
  persistent is ~300–400 LOC. (AnythingLLM — MIT, best turnkey app — stays an *optional* QuickTools
  iframe only. LlamaIndex-core is a sanctioned *accelerator* if citation/incremental-reindex
  plumbing gets tedious — pull only sub-packages, never the meta package.)
- **NL agent (Gemini drives SelfX):** a **custom function-calling gateway**, not MCP. `GET /tools`
  already emits per-tool JSON-Schema → a ~30-line converter turns each into a Gemini
  `FunctionDeclaration` *and* an Ollama `tools[]` entry (one list, both brains). google-genai SDK =
  cloud brain; extend `_ollama.chat` = local brain. **Disable automatic function calling** — intercept
  the `FunctionCall`, run it through SelfX's *own validated* job pipeline, poll, return a *small*
  `FunctionResponse` (file_ids/names/status — never bytes). `SELFX_AGENT_PROVIDER=ollama` default
  (offline), `gemini` opt-in when `GEMINI_API_KEY` is set. Model: **gemini-2.5-flash** for routing.
  (FastMCP is an *optional later* add for cross-assistant interop — Claude Desktop etc.)

## Architecture (two native surfaces bolt onto the existing FastAPI app; zero new heavy services)

- **Data (`server/app/kb/`)** on the already-provisioned pgvector image: `Collection`, `Document`,
  `Chunk(embedding Vector(768), tsv tsvector)`, `KbMessage`. `ensure_schema()` runs at API + worker
  startup: `CREATE EXTENSION IF NOT EXISTS vector` → `create_all` → idempotent HNSW
  (`vector_cosine_ops`) + GIN(tsv) indexes. KB chunks are exempt from `FILE_RETENTION_HOURS`.
- **Ingestion** = a registry tool `kb-ingest` (queue=heavy) so UI *and* agent drive it through the
  same `/api/v1/jobs` contract: Docling/`_text_extract` parse (+OCRmyPDF for scans) → reuse
  `multi_doc_qa._chunk` (page/section metadata for citations) → `_ollama.embed_batch` → upsert
  `Chunk` rows with `content_hash` dedup. Inherits progress/cancel/timeout from RQ for free.
- **Retrieval + synthesis** stay in the **API** (not the worker, so they work in native-Windows dev):
  `kb.retrieve()` = pgvector cosine `<=>` top-k + Postgres `ts_rank`, RRF-merged → passages+citations;
  `kb.answer()` = grounded prompt → provider (Ollama default, Gemini per-collection opt-in).
  `routes/kb.py`: collections CRUD, ingest (enqueue), `POST /kb/collections/{id}/chat` (SSE+sync).
- **Agent (`server/app/agent/`)**: `schema_convert` (registry→FunctionDeclaration/Ollama tools),
  `loop` (provider-agnostic), `gemini.py` (google-genai, auto-FC off), `ollama_agent.py`
  (`/api/chat` tool_calls), `tools_bus` (dispatch → `services.jobs.create_and_run_job` for real tools,
  or instant in-process `kb_search` / `find_files`). `routes/agent.py: POST /api/v1/agent/chat`.
- **Shared job choke-point:** refactor the validate+persist+enqueue core of `routes/jobs.create_job`
  into `server/app/services/jobs.create_and_run_job(...)` so route AND agent enforce the *same*
  ownership / availability / MIME / jsonschema / rate-limit gates.
- **Frontend (native pages, not iframes):** `KnowledgeBase.tsx` (collections, drag-drop ingest via
  FileDrop + job polling, streaming chat with clickable citation chips) and `Agent.tsx` (chat +
  tool-call/job cards + Local/Gemini toggle + download links).

## Privacy

**Local (never leaves the box):** all file bytes (worker-only, in `/data`), the pgvector store, all
embeddings (local `nomic-embed-text`), and — on the default `ollama` provider — every LLM token
(fully air-gapped, no key). **To Google only on explicit opt-in:** the NL request text, tool schemas,
and small result summaries. Guardrails: provider defaults to `ollama`; Gemini disabled until
`GEMINI_API_KEY` set; content-bearing tool summaries (kb_search/extract-text/transcribe/ocr)
default-redact/limit what they hand the model; files referenced only by UUID, never uploaded to
Google; recommend paid Gemini/Vertex (`GEMINI_USE_VERTEX`) for sensitive corpora (free tier may train
on prompts).

## Build order (each step verifiable)

1. **Foundation:** `apt install postgresql-16-pgvector` in WSL; add `pgvector` Python dep; `kb/models.py`
   + `kb/schema.ensure_schema()` (extension → create_all → HNSW+GIN); config `KB_EMBED_MODEL`,
   `KB_EMBED_DIM=768`. Call ensure_schema from `main.lifespan` + `worker.main`.
2. **Shared job service:** extract `services/jobs.create_and_run_job(...)`; make `routes/jobs.create_job`
   a thin caller.
3. **KB ingest:** `kb/ingest.py` (parse→chunk→embed_batch→upsert w/ content_hash dedup) wrapped as
   `tools/kb_ingest.py` (queue=heavy).
4. **KB retrieve+answer:** `kb/retrieve.py` (pgvector + ts_rank, RRF), `kb/answer.py`; extend
   `_ollama.chat` for streaming + optional `tools`.
5. **KB API+UI:** `routes/kb.py`; `web/src/pages/KnowledgeBase.tsx`.
6. **Agent schema bridge:** `agent/schema_convert.py`; add `agent_exposed` flag/allowlist on Tool;
   instant fns `kb_search`, `find_files`.
7. **Agent gateway:** `agent/{loop,gemini,ollama_agent,tools_bus}.py`; config `GEMINI_API_KEY`
   (unset=disabled), `GEMINI_MODEL=gemini-2.5-flash`, `GEMINI_USE_VERTEX=false`,
   `SELFX_AGENT_PROVIDER=ollama`.
8. **Agent API+UI:** `routes/agent.py`; `web/src/pages/Agent.tsx`.
9. **Privacy/guardrails:** default local; explicit cloud opt-in; redact content-bearing summaries;
   per-collection allow-cloud flag; per-user cost/rate caps.
10. **Later (non-blocking):** Alembic (before these tables change); optional FastMCP server for
    cross-assistant interop; harden SSE.

## Key risks
- Embedding-dim lock-in `Vector(768)`↔nomic — store `embed_model` per Collection, refuse cross-model.
- Free-tier Gemini may train on prompts/snippets — default local, gate cloud, recommend Vertex.
- Content leak via result summaries — default-redact content-bearing tool outputs bound for cloud.
- No Alembic yet — keep `ensure_schema` idempotent; add Alembic before schema changes.
- Tool-routing quality with ~60 tools — curate an `agent_exposed` subset + crisp descriptions; qwen3
  for the local agent brain.
- Validation bypass — the agent MUST use the single `create_and_run_job` choke-point.
- RQ worker is Linux/fork-only — keep retrieval+chat in the API so doc-chat/agent work in native dev.
