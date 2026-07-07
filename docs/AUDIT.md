# SelfX — Feature Audit & Improvement Backlog

_Generated from a 10-agent code audit (9 analyzers reading every adapter + infra + UI, plus a synthesis pass) combined with live functional and edge-case testing on the running instance. Companion to [REPORT.md](REPORT.md) and [SPEC.md](SPEC.md)._

## How this was tested

- **Functional:** all 48 tools driven end-to-end through the real API → queue → worker → engine → download (`scratchpad/api_smoke.py`). **47/47 runnable pass**; image-upscale was GPU-gated at audit time (now enabled).
- **Edge / abuse:** a dedicated suite (`scratchpad/edge_test.py`) exercised auth, upload/job validation, ownership isolation, archive guards, malformed inputs, cancellation and concurrency — **25/27 pass** (the 2 'failures' were the test's wrong expectations: empty uploads are rejected by design, and file-reuse is correctly blocked).
- **Code analysis:** every adapter + the infra/API/security/worker + the frontend were read line-by-line for edge cases, performance, robustness and broader-format support.

## Test scorecard

| Area | Result |
|---|---|
| 48 tools functional (happy path) | ✅ 47/47 runnable pass |
| Auth (missing / bad / wrong creds) | ✅ 401s correct; healthz public |
| Ownership isolation (user B vs A) | ✅ can't read jobs / download files / hit admin |
| Archive zip-bomb + path-traversal | ✅ both rejected |
| Job validation | ✅ 404 unknown · 400 count · 422 ext/enum/param · 409 gated/reuse |
| Corrupt inputs | ✅ graceful ToolError, no crash |
| Cancellation + 8 concurrent jobs | ✅ handled |
| Streamed upload cap / empty-reject / sniff / sanitize | ✅ implemented |

---

## Executive summary — prioritized

The suite is functionally solid and secure on the fundamentals; the findings below are about correctness edge cases, performance, and reach. Ranked most-important first.

### 🔴 Highest-priority edge cases / correctness

1. **CONTEXT-WINDOW TRUNCATION on every LLM call: _ollama.chat() sends no options.num_ctx, so Ollama applies its 2048-token default and silently LEFT-truncates the prompt — dropping the system message, the length/answer instruction, and the START of the document/passages. Summaries and QA answers are computed only from the tail of the input, and doc-qa wrongly replies 'not in the document'. Silent wrong output, hits real inputs every time a doc exceeds ~1.5k tokens.**  — _critical_ · `ai-rag/_ollama.chat -> ai-summarize, doc-qa, multi-doc-qa, audio-summary`
2. **OWNER-PASSWORD / PERMISSION STRIPPING: pikepdf opens an owner-password-only PDF (print/copy/edit restricted, empty user pw) with NO password, and merge/split/rotate then save an UNENCRYPTED copy, silently removing the restrictions with no password supplied. Turns three innocuous tools into a permission remover.**  — _high_ · `pdf-merge, pdf-split, pdf-rotate`
3. **SSRF / local-file read: WeasyPrint's default url_fetcher resolves file://, http(s):// and relative URLs in-process, so uploaded HTML with <img src='file:///etc/passwd'> or 'http://169.254.169.254/...' is fetched and embedded/exfiltrated. The 'remote resources are not fetched' claim is false and a successful fetch raises nothing, so it isn't caught.**  — _high_ · `documents/html-to-pdf (WeasyPrint)`
4. **SSRF + unbounded download in media-download: yt-dlp fetches any http(s) target with no host allowlist / no private-range block (localhost, 127.0.0.1, 169.254.169.254 metadata, LAN), runs in-process so job_timeout doesn't apply, has no max_filesize/disk guard, and a live-stream URL never terminates until disk fills.**  — _high_ · `media/media-download`
5. **RAG 200-chunk cap has an ORDERING BIAS: passages are appended in upload order then sliced [:200], so with many/large docs the cap is filled by the FIRST files and LATER DOCUMENTS ARE DROPPED ENTIRELY. A question answerable only from doc #8 silently fails, and the 'only first passages indexed' note undersells that whole files were skipped.**  — _high_ · `ai-rag/multi-doc-qa`
6. **Non-UTF-8 subtitle inputs fail or mojibake: no -sub_charenc (ffmpeg) / --encoding (ffsubsync) is passed, so extremely common legacy subs in Windows-1256 (Arabic), CP1251 (Cyrillic), GBK/Big5, Shift-JIS, Latin-1, and UTF-16/BOM either abort ('Invalid UTF-8') or silently corrupt. Affects a large fraction of real downloaded subs.**  — _high_ · `subtitle-convert, subtitle-extract, subtitle-sync`
7. **THINKING-TOKEN LEAKAGE: the committed default chat model is qwen3:8b (a reasoning model) and _ollama.chat sends no think:false and returns content verbatim, so raw <think>...</think> chain-of-thought can be written into summary/answer/notes output files (and burns large CPU-time per call).**  — _high_ · `ai-rag/_ollama -> all AI tools`
8. **safe_suffix keeps only the final Path.suffix, destroying compound extensions at upload: 'backup.tar.gz' is stored as <uuid>.gz, so archive-extract (which dispatches on the stored suffix) only GUNZIPS and never UN-TARS — the user gets an unusable single .tar back instead of extracted files.**  — _high_ · `utilities/storage.safe_suffix + archive-extract`
9. **In-process operations bypass run_cmd's 1800s timeout entirely: WeasyPrint (write_pdf) can wedge the worker indefinitely on a pathological doc; noisereduce, audio-separator, yt-dlp, faster-whisper, and the blocking Ollama call are bounded only by the RQ worker timeout and cannot be cooperatively cancelled mid-run.**  — _high_ · `html-to-pdf, speech-denoise, voice-isolation, media-download, transcribe, _ollama`
10. **No decompression-bomb / pixel cap on any PIL tool: a valid large image raises DecompressionBombError (swallowed as 'not a readable image'), and within the 512MB upload cap a small highly-compressed PNG or uncompressed BMP/TIFF can decode to multi-GB RAM and OOM the CPU-only worker. pdf-to-images compounds this by capping DPI (600) but not page dimensions, so an A0 page renders a multi-hundred-megapixel bitmap.**  — _high_ · `image-convert, image-optimize, image-to-ico, pdf-to-images`
11. **subtitle-extract reports 'no embedded subtitle track found' for image-based tracks (Blu-ray PGS, DVD VobSub, DVB bitmap) that ffmpeg can't encode to text SRT. The track EXISTS and needs OCR, but the user is actively told it doesn't exist; out-of-range index and corrupt streams collapse into the same misleading message.**  — _high_ · `subtitles/subtitle-extract`
12. **pdf-to-images JPEG BLACK BACKGROUND: pil.convert('RGB') on an RGBA render drops the alpha channel without compositing, so transparent PDF regions become BLACK instead of white. Should paste onto a white background first.**  — _medium_ · `pdf/pdf-to-images`
13. **EXIF Orientation ignored everywhere: metadata is stripped by default but pixels are never transposed, so phone photos tagged with a rotation come out sideways/upside-down after convert/optimize/ico, and images-to-pdf saves them rotated. One ImageOps.exif_transpose() before save/inference fixes all of them.**  — _medium_ · `image-convert, image-optimize, image-to-ico, image-caption, images-to-pdf`

### ⚡ Highest-impact optimizations

1. **BATCH EMBEDDINGS: replace up to 200 sequential POSTs to the deprecated singular /api/embeddings with a single (or few) array request(s) to /api/embed. The single biggest speedup in the RAG path — turns 200 round-trips into ~1.**  — _high_ · `ai-rag/multi-doc-qa + _ollama.embed`
2. **Per-worker per-model cache: rembg builds a fresh session every job, image-upscale reloads the .pth and re-.cuda()s every job, pdf-to-markdown re-instantiates DocumentConverter (reloading the Docling pipeline) every job, and voice-isolation loads a separate ONNX model copy per job. Standardize a module-level dict keyed by model name (as image-to-text already does) so a warm worker reuses loaded models.**  — _high_ · `image-remove-bg, image-upscale, pdf-to-markdown, voice-isolation`
3. **Pre-bake model weights into the image and set offline env: rembg U2Net, RealESRGAN, Docling layout models, MDX-NET stems, and moondream all download at first use, which BOTH fails on air-gapped WSL and pays a large cold-start cost. Bundling removes the network round-trip and speeds first run.**  — _high_ · `image-remove-bg, image-upscale, pdf-to-markdown, voice-isolation, image-caption`
4. **Stream Ollama responses with keep_alive set: non-streaming stream:False with read=600s hits the timeout on an 8B CPU generation (surfaced as 'could not reach Ollama' with zero output), and the model is reloaded when it goes cold between jobs. Streaming + keep_alive fixes the timeout, keeps the model resident, and enables real progress.**  — _high_ · `ai-rag/_ollama -> all AI tools`
5. **Stream-copy / remux fast path when the requested codec already matches the input: media-convert can '-c:v copy -c:a copy' for a container change, audio-extract can '-c:a copy' (mp3->mp3, aac-in-mp4->m4a), and video-trim can offer keyframe-aligned '-c copy'. Turns full re-encodes into near-instant, lossless operations.**  — _high_ · `media-convert, audio-extract, video-trim`
6. **CPU-tune the encoders on this CPU-only box: webm-vp9 uses libvpx defaults (cpu-used 0 / deadline good = brutally slow, and no -crf when omitted) so a few-minute 1080p clip can blow the 1800s timeout — add -cpu-used 4 -deadline good -tile-columns; whisper should set cpu_threads/num_workers and lower beam_size (5->1-2); x264 preset should drop from 'medium' to 'veryfast'.**  — _high_ · `media-convert, transcribe, video-trim`
7. **Write already-compressed bytes straight into a ZIP_STORED archive via BytesIO instead of writing per-page temp files and re-DEFLATEing them: PDF page streams and PNG/JPEG gain almost nothing from DEFLATE while costing CPU and double I/O; archive-compress likewise re-DEFLATEs jpg/png/mp4/zip inputs.**  — _medium_ · `pdf-split (burst), pdf-to-images, archive-compress`
8. **Downscale images before AI inference: image-caption base64-encodes the full upload (a 512MB file becomes a ~683MB JSON body) when moondream only needs ~768-1024px; remove-bg infers at 320x320 anyway; OCR/caption/remove-bg should downscale oversized inputs first — cuts payload ~100x, speeds inference, and sidesteps BMP/TIFF/GIF decode issues.**  — _high_ · `image-caption, image-remove-bg, image-to-text`
9. **Fix PDF text extraction cost/quality: _from_pdf parses ALL pages then truncates, so a 10k-page PDF is fully parsed for 24k chars — early-exit the page loop once the accumulated length reaches max_chars, and swap slow pypdf for pypdfium2/PyMuPDF (already a dependency elsewhere) for faster, higher-fidelity text.**  — _medium_ · `ai-rag/_text_extract, pdf-extract-text`
10. **Avoid metadata-remove's copy-then-rewrite: shutil.copy2 duplicates up to 512MB and then exiftool overwrites in place; use 'exiftool -o <output_dir>/name' to write the stripped file in one pass, and consider -stay_open to amortize the ~100-200ms Perl startup on repeated use.**  — _medium_ · `utilities/metadata-remove`

### ✨ Highest-value improvements

1. **Thread the original filename through to downloads so users stop getting UUID-gibberish names: 8/12 PDF tools, nearly every media tool, transcribe, and archive entries derive output names from src.stem (a UUID). Either carry the original stem in ToolContext/params or map UUID->original name at the download layer.**  — _high_ · `pdf-* (compress/rotate/protect/unlock/watermark/extract-text/to-docx/to-images/to-markdown), media-*, transcribe, archive-compress/extract`
2. **Emit real progress by parsing the underlying engine output instead of static 0.2/0.3->1.0 jumps: gs page output, pdf2docx/ocrmypdf per-page callbacks, ffmpeg -progress, ffsubsync stderr phases, and Ollama streaming all expose progress. Long OCR/ebook/office/transcription jobs currently look frozen for minutes.**  — _high_ · `pdf-compress, pdf-to-docx, ocr-pdf, subtitle-sync, all AI tools, media tools`
3. **Never hand back a bigger file than the input: pdf-compress (Ghostscript re-encode can inflate) and image-optimize (BMP/TIFF/HEIC->PNG, negative '-120% smaller') both write a larger output labeled 'compressed'/'optimized'. Compare sizes and return the original (or report no gain) instead.**  — _high_ · `pdf-compress, image-optimize`
4. **Give distinct, friendly error messages per failure class instead of one generic string: encryption ('unlock first'), image-based subtitle track ('use OCR'), model-download/network failure vs unsupported image, not-encrypted vs wrong-password, out-of-range vs image-based vs absent subtitle track, and OOM vs bad-image.**  — _high_ · `pdf-compress, subtitle-extract, image-remove-bg, image-upscale, pdf-unlock, _ollama`
5. **Chunk/map-reduce long-document summarization instead of hard-truncating to the first 24000 chars, and add a truncation note where missing (audio-summary silently drops the back half of a 2-hour meeting with no warning; doc-qa should auto-delegate to the RAG tool rather than answer 'not found').**  — _high_ · `ai-summarize, audio-summary, doc-qa`
6. **Add an available() preflight on every adapter for a clean 409 instead of accepting a job that fails at runtime: pandoc-convert and ocr-pdf lack it, transcribe doesn't validate the language code, and _ollama.available() never verifies the configured chat model is actually pulled.**  — _medium_ · `pandoc-convert, ocr-pdf, transcribe, _ollama`
7. **Apply EXIF orientation (ImageOps.exif_transpose) before saving/inference across all image tools so metadata-stripped photos aren't rotated, and composite RGBA onto white before JPEG conversion (with an exposed background/quality param) so transparent regions don't go black.**  — _high_ · `image-convert, image-optimize, image-to-ico, image-caption, images-to-pdf, pdf-to-images`
8. **Register a bundled Unicode TTF (DejaVu/Noto) for the watermark overlay so CJK/RTL/accented text renders instead of tofu, and apply the page's /Rotate and CropBox origin so the stamp lands correctly on rotated/cropped pages.**  — _medium_ · `pdf-watermark`
9. **Preserve PDF navigation and accessibility across every re-saving transform: bookmarks/outlines, named destinations, page labels, AcroForm fields, tagged-PDF structure, and XMP metadata are dropped (merge orphans forms and loses per-file bookmarks; gs-compress and pdf2docx drop tags), and existing digital signatures are silently invalidated with no warning.**  — _medium_ · `pdf-merge, pdf-split, pdf-compress, pdf-rotate, pdf-to-docx`
10. **Detect input charset (charset-normalizer) and normalize to UTF-8 for all text pipelines, and validate SEMANTIC output (>=1 real cue / >=1 page) rather than just st_size>0 — today a header-only 'WEBVTT\n\n', a zero-cue extract, a garbage-offset sync, and a blank office->PDF all pass as success.**  — _medium_ · `subtitle-convert/extract/sync, _text_extract, office-convert`

### 🔁 Recurring themes (worth a single platform-level fix)

- UUID FILENAMES LEAK TO DOWNLOADS SUITE-WIDE: inputs are stored as <uuid><suffix> and almost every tool derives its output name from src.stem, so users download <uuid>-compressed.pdf / <uuid>.txt / <uuid>-thumb.jpg. Compounded by _rename_outputs only renaming top-level files (not zip arcnames or inner extract names), gz dropping the extension, and safe_suffix truncating compound extensions ('.tar.gz'->'.gz'). One platform fix: thread orig_name through ToolContext and map UUID->original at download.
- MODELS LOADED PER-JOB INSTEAD OF PER-WORKER, AND DOWNLOADED AT RUNTIME: rembg, image-upscale, Docling (pdf-to-markdown), and voice-isolation each rebuild/reload their model every request, and rembg/RealESRGAN/Docling/MDX/moondream all fetch weights from the internet on first use — which both fails on the air-gapped WSL deployment and masks the real cause as 'bad image'. Fix: a standard per-worker per-model singleton cache plus offline pre-baked weights, with network-vs-bad-input errors kept distinct.
- NO num_ctx / STREAMING / think:false ON THE SHARED OLLAMA CLIENT: a single _ollama fix (size num_ctx to the prompt, stream to beat the 600s read timeout and drive progress, keep_alive to stay warm, think:false to stop reasoning-token leakage, empty-output guard, and batch /api/embed) simultaneously repairs the headline truncation bug, the CoT-leak bug, and the timeout/perf issues across ai-summarize, doc-qa, multi-doc-qa, and audio-summary.
- IN-PROCESS OPERATIONS BYPASS run_cmd's TIMEOUT: only subprocess tools are time-bounded, so WeasyPrint, noisereduce, audio-separator, yt-dlp, faster-whisper, and the blocking Ollama call can run past the 1800s budget or hang the worker indefinitely and cannot be cancelled. Needs a worker-level watchdog / subprocess wrapper for all in-process converters and inference calls.
- SUCCESS JUDGED ONLY BY out.stat().st_size>0: header-only subtitles ('WEBVTT\n\n'), zero-cue extracts, garbage-offset syncs, blank office->PDF outputs, and ICOs with no real entries all report success. A shared 'semantic output valid (>=1 cue / >=1 page / >=1 image entry)' check would make every group report failures honestly.
- FILE TYPE TRUSTED BY FILENAME EXTENSION ALONE: only ARCHIVE_MIMES gets a content/MIME cross-check; document, image, subtitle, and media categories accept whatever the suffix claims, so a mislabeled or dotfile-only ('.docx'->empty stored suffix) file reaches the wrong/undetectable engine and dies deep with a raw stderr tail instead of a clean 422 at submit. Add a lightweight content sniff for all categories.
- RE-COMPRESSING ALREADY-COMPRESSED DATA WITH DEFLATE + DOUBLE TEMP-FILE I/O: pdf-split burst, pdf-to-images, and archive-compress write per-item temp files then DEFLATE PDF/PNG/JPEG streams that don't shrink. Standard fix: render/extract into BytesIO and store with ZIP_STORED.
- PROGRESS IS COSMETIC ACROSS THE SUITE (static 0.2-0.4 then 1.0): almost every long-running tool ignores the per-page/percent output its engine already emits (gs, pdf2docx, ocrmypdf, ffmpeg -progress, ffsubsync, Ollama stream), so multi-minute jobs look frozen.
- NO OUTPUT-SIZE OR FREE-DISK GUARD: only uploads are capped (512MB). media-convert's uncapped gif preset, gif-from-video at max params, media-download (no max_filesize), OCR PDF/A bloat, image-heavy ebook conversion, and speech-denoise can each produce huge outputs or exhaust disk. Needs a per-job output ceiling + free-space precheck.
- EXIF ORIENTATION IGNORED AND MODE HANDLING INCONSISTENT ACROSS ALL PILLOW TOOLS: no exif_transpose anywhere (sideways photos), CMYK/16-bit/grayscale handling is buggy per tool, animated/multi-frame inputs silently reduce to frame 0, and a broad 'except Exception -> one generic message' collapses OOM/network/format/timeout. A shared normalize-mode + transpose + decompression-bomb-guard + labeled-error helper would harden convert/optimize/ico/caption at once.
- LOSSY RE-ENCODE AT DEFAULT BITRATE SILENTLY DOWNGRADES AUDIO: audio-extract (same-codec), audio-normalize (192kHz upsample + libmp3lame defaults), and speech-denoise re-encode a 320kbps source down to ~128kbps. A shared copy-when-codec-matches fast path plus source-bitrate carry-over preserves quality and speed.
- ENCODING/CHARSET NOT HANDLED FOR TEXT INPUTS: subtitles (no -sub_charenc/--encoding), .txt extraction (errors='replace' mangles Windows-1252/UTF-16/BOM), and docx (paragraphs only, tables/headers/footers dropped) all lose or corrupt real-world non-UTF-8 content. A shared detect-charset-normalize-to-UTF-8 + richer-docx extractor helper fixes convert, extract, sync, summarize, and QA together.
- CPU-ONLY DEPLOYMENT WITH DOCKER-ASSUMED DEFAULTS: enum options and encoder defaults assume the bundled Docker image (Gotenberg for landscape, tesseract eng/deu/fra/spa) and GPU/fast codecs, but the real deployment is WSL-no-Docker on CPU — landscape silently no-ops, deu/fra/spa OCR fails at runtime, and vp9/whisper/MDX defaults are 1800s-timeout candidates. Tune defaults for CPU and gate options on what is actually installed.

---

## Feature inventory

| Group | Features analyzed |
|---|---|
| PDF tools | 12 |
| Image tools | 7 |
| Document tools | 5 |
| Media / audio / video tools | 9 |
| Subtitle tools | 3 |
| AI & RAG tools | 7 |
| Utility tools | 7 |
| Infrastructure · API · security · worker | 11 |
| Frontend & UX | 11 |
| **Total** | **72** |

---

## Detailed findings by group

### PDF tools

**Cross-cutting for this group:**

- OUTPUT FILENAMES LEAK UUIDs: 8 of 12 tools name their output from `src.stem` (compress, rotate, protect, unlock, watermark, extract-text, to-docx, to-images, to-markdown). Because input_paths are absolute uuid-named paths, the user downloads e.g. `3f9c1a2b-...-compressed.pdf` / `<uuid>.txt` instead of `<original-name>-compressed.pdf`. The original filename is never threaded through ToolContext. This is a suite-wide UX defect; the download layer should either carry the original stem in params or the framework should map UUID->original name on download.
- OWNER-PASSWORD / PERMISSION STRIPPING: pikepdf.open() opens a PDF that has ONLY an owner password (print/copy/edit restrictions, empty user password) WITHOUT any password. pdf-merge, pdf-split, and pdf-rotate then save an UNENCRYPTED copy, silently removing those restrictions with no password supplied. This effectively turns three innocuous tools into an owner-password/permission remover. If that is not intended, add an is_encrypted pre-check and refuse (or require the password) the way pdf-watermark/extract-text do.
- DIGITAL SIGNATURES SILENTLY INVALIDATED: every tool that re-saves the PDF (merge, split, compress via Ghostscript, rotate, protect, unlock, watermark) rewrites the file and thus breaks any existing digital/e-signature, with no warning to the user. Consider detecting /Sig fields and warning.
- PASSWORD PARAMS IN JOB ROW: pdf-protect and pdf-unlock receive the cleartext password via ctx.params. Confirm the params dict is NOT persisted/logged into the jobs table or worker logs; if it is, user PDF passwords are stored in the DB. Redact password-typed fields at persistence time.
- METADATA / BOOKMARKS / OUTLINES / FORMS DROPPED: none of the transforming tools preserve document outline (bookmarks), named destinations, AcroForm fields, page labels, tagged-PDF structure (accessibility), or XMP metadata. merge in particular loses per-file bookmarks and orphans form fields; gs-compress and pdf2docx drop tags. This degrades accessibility and navigation across the group.
- ZIP TOOLS DOUBLE-I/O AND WASTE CPU: pdf-split (burst) and pdf-to-images write each page to a temp file on disk, then read it back to add to a ZIP_DEFLATED archive. PDF page streams and PNG/JPEG are already compressed, so DEFLATE gains almost nothing while costing CPU. Write bytes straight into the zip via BytesIO and use ZIP_STORED.
- STATIC/COARSE PROGRESS: pdf-compress (0.2->1.0), pdf-to-docx (0.2->1.0), and pdf-to-markdown (0.3->1.0) report only two progress points because the underlying engines (Ghostscript, pdf2docx, Docling) run as one opaque call; long jobs look frozen. Consider parsing gs page output or pdf2docx per-page callbacks.
- PER-PAGE ERRORS ABORT WHOLE JOB: pdf-extract-text and pdf-watermark loop pages with no per-page try/except, so a single malformed page raises and fails the entire multi-hundred-page job. Wrap per-page work and continue/collect.

#### Merge PDFs  ·  `pdf-merge`  ·  _concern_

- **Edge cases:**
    - FOREIGN-PAGE COPY LIFETIME: each source is opened in a `with` block that CLOSES it at the end of every iteration, but `merged.save()` runs AFTER the loop when every source is already closed. `merged.pages.extend(src.pages)` relies on pikepdf having eagerly copied all indirect resources (shared fonts, images, XObjects via copy_foreign) before close. Simple PDFs (happy path) work, but PDFs with shared/indirect resource dictionaries risk missing objects or a corrupt merged file. Verify by merging complex PDFs (embedded fonts, form XObjects) and keep sources open until save.
    - AcroForm fields from multiple inputs are neither merged nor renamed: duplicate field names collide and interactive forms end up broken/orphaned in the output.
    - Owner-password-only encrypted inputs open without a password and are merged into an UNENCRYPTED output (see cross-cutting security note).
    - Bookmarks/outlines, named destinations, page labels, JavaScript, and document-level metadata of all inputs are discarded.
    - No upper bound on file count or total pages beyond min_files=2; the full merged document is held in memory until save, so hundreds of large PDFs can exhaust worker memory.
    - Mixed/rotated page geometries are carried verbatim (fine) but there is no normalization option.
- **Optimizations:**
    - Keep each source open until after `merged.save()` (a list of open handles closed in one finally) to guarantee eager foreign-object copying and avoid re-resolving references.
    - Stream/save incrementally is not possible with pikepdf, but calling `merged.remove_unreferenced_resources()` before save can shrink output when inputs share objects.
- **Improvements:**
    - Add a per-file bookmark (outline entry) so the merged doc is navigable.
    - Copy the first document's metadata (or let the user pick) instead of dropping all XMP/Info.
    - Detect and either merge or uniquify AcroForm field names.
- **Broader support:**
    - Per-file page-range selection and interleaving/reordering rather than strict upload order.
    - Accept images (jpg/png) as inputs and auto-wrap them as pages.
    - Optional table-of-contents / blank-separator-page insertion between files.

#### Split PDF  ·  `pdf-split`  ·  _verified-working_

- **Edge cases:**
    - No open-ended range syntax: '5-' (page 5 to end) and '-3' both hit int('') -> 'invalid page range'. Users cannot express 'from page N to end' without knowing the total.
    - Burst mode (empty spec) on a very large PDF writes one temp .pdf per page to workdir then zips them: a 10k-page document creates 10k temp files and 10k pikepdf.new()/copy_foreign round-trips — slow and I/O heavy.
    - ZIP_DEFLATE is applied to already-compressed PDF streams (near-zero size gain, wasted CPU).
    - Dedup check `(n-1) not in pages` is O(n^2), but maxLength=200 on the spec keeps it bounded — acceptable.
    - Extracted output ('split.pdf') loses bookmarks/outlines/metadata that pointed into the kept pages.
    - Reversed ('7-3'), zero/negative, and non-numeric specs are correctly rejected.
- **Optimizations:**
    - In burst mode, save each one-page PDF to a BytesIO and write bytes directly into the zip (use ZIP_STORED), eliminating the temp-file write+read cycle.
    - Reuse a single output document object where possible instead of new pikepdf.new() per page.
- **Improvements:**
    - Support 'N-' (to end) and open ranges; also support inverse selection (all pages EXCEPT the spec).
    - Carry over bookmarks/metadata whose destinations fall within extracted pages.
    - Report the resulting page count / file count in the final progress message.
- **Broader support:**
    - Split by chunk size (N pages per file) or by top-level bookmarks/chapters.
    - Split by target file size.
    - Option to always return a zip even for a single extracted range, or to name each burst page after its page number in a user-facing way.

#### Compress PDF  ·  `pdf-compress`  ·  _concern_

- **Edge cases:**
    - OUTPUT CAN BE LARGER THAN INPUT: Ghostscript's pdfwrite re-encode inflates already-optimized, vector-heavy, or text-only PDFs. The code only checks size>0, never compares against the source, so the user can receive a bigger file labeled '-compressed'.
    - Password-protected input: gs -dSAFER fails on encryption and the raw gs stderr tail is surfaced (e.g. 'This file requires a password'); there is no friendly pre-check like the pikepdf tools have.
    - gs pdfwrite drops PDF/A conformance and tagged-PDF structure (accessibility) and may re-subset fonts; non-embedded/unusual fonts can render differently.
    - Digital signatures are invalidated (file is rewritten).
    - Large PDFs can hit the job timeout inside a single opaque gs call with only 0.2 progress shown.
    - gs sometimes 'repairs' a corrupt PDF and exits 0 with degraded content rather than failing, so the size>0 guard passes on garbage output.
- **Optimizations:**
    - Add `-dDetectDuplicateImages=true` to dedupe repeated images, plus `-dCompressFonts=true -dSubsetFonts=true`.
    - Add `-dFastWebView=true` to linearize for streaming download.
    - Compare out_path size to src size and, if not smaller, return the original (or note that no gain was achieved) to avoid handing back a bigger file.
- **Improvements:**
    - Pre-detect encryption with pikepdf and give a friendly 'unlock first' message instead of raw gs stderr.
    - Report before/after size and percentage saved in the final progress message.
    - Expose explicit image DPI / JPEG quality and an optional grayscale-conversion flag rather than only the 3 canned presets.
- **Broader support:**
    - Target-file-size mode (iterate settings/DPI to hit a size).
    - Grayscale/monochrome downconversion option for scans.
    - Preserve-metadata flag (gs can drop Info/XMP).

#### Rotate PDF  ·  `pdf-rotate`  ·  _verified-working_

- **Edge cases:**
    - Rotates ALL pages by the same angle only; cannot rotate a subset or apply different angles per page.
    - Only 90/180/270 clockwise; no arbitrary or counter-clockwise-by-name option (270 stands in for CCW).
    - Owner-password-only encrypted input opens without a password and is saved UNENCRYPTED, stripping restrictions (cross-cutting security note).
    - Digital signatures invalidated by the re-save.
    - Existing /Rotate values are correctly added relatively and normalized by pikepdf (good).
- **Optimizations:**
    - Rotation only touches the /Rotate dict entry, so it is already cheap; optionally save with `linearize=True` at no real cost for faster web view.
    - For huge files, qpdf/pikepdf could rewrite without fully re-serializing streams — current approach is fine but reserializes everything.
- **Improvements:**
    - Add a page-range param so users can fix a single sideways scan page.
    - Offer 'auto-straighten' presets and preserve bookmarks/metadata (currently preserved by pikepdf save — keep it that way).
    - Add an is_encrypted/owner-only guard consistent with the rest of the suite.
- **Broader support:**
    - Per-page angle map (e.g. '1:90,3:180').
    - Horizontal/vertical flip (mirror).
    - Rotate only odd/even pages (common for duplex scans).

#### Password-protect PDF  ·  `pdf-protect`  ·  _concern_

- **Edge cases:**
    - owner==user password: the same string is used for both, so anyone who can OPEN the file also has OWNER rights — permission restrictions (no-print/no-copy) are meaningless. A distinct owner password is required to enforce permissions.
    - UNICODE PASSWORD TRUNCATION: maxLength=128 counts characters, but the PDF security handler is limited to 127 BYTES (SASLprep/UTF-8). A multibyte (CJK/emoji/accented) password over 127 bytes is silently truncated during encryption, so the user's typed password may not open the file.
    - An owner-only-encrypted input opens without a password and is silently RE-encrypted with the new password (double-handling), rather than being rejected as 'already protected'.
    - Cleartext password flows through ctx.params — verify it is not logged/persisted (cross-cutting).
- **Optimizations:**
    - Encryption is cheap (single re-save); no perf concern.
- **Improvements:**
    - Separate owner and user password fields, plus permission flags (allow print / copy / modify / annotate).
    - Warn or reject when the byte-length of the password exceeds the 127-byte handler limit.
    - Add a password-strength hint and confirm-password UX.
- **Broader support:**
    - Selectable encryption strength (AES-128 / RC4-128) for compatibility with older readers that cannot open R6/AES-256.
    - Certificate/public-key based encryption for enterprise recipients.

#### Unlock PDF  ·  `pdf-unlock`  ·  _verified-working_

- **Edge cases:**
    - Ambiguous error path: an UNENCRYPTED input passed with any password raises pikepdf.PasswordError -> 'wrong password, or the PDF is not password-protected' (message covers it, but the two cases are conflated).
    - For an owner-only-encrypted file (empty user password), pikepdf may open even with an incorrect supplied password (empty-user-pw fallback), so a 'wrong' password can still succeed — surprising but not harmful.
    - Removes ALL restrictions (legitimate, since the caller supplied the password) — but a signed document's signature is invalidated by the re-save.
    - Cleartext password via ctx.params — same persistence/logging caution as pdf-protect.
- **Optimizations:**
    - Single re-save; no perf concern.
- **Improvements:**
    - Distinguish 'not encrypted' from 'wrong password' for a clearer message (check reader.is_encrypted before attempting).
    - Optionally preserve metadata/permissions the user wants to keep while only removing the open password.
- **Broader support:**
    - Batch-unlock multiple PDFs sharing one password.
    - Try-empty-password mode to strip owner-only restrictions explicitly (with a clear consent prompt).

#### Watermark PDF  ·  `pdf-watermark`  ·  _concern_

- **Edge cases:**
    - NON-LATIN TEXT BREAKS: the overlay uses reportlab's built-in Helvetica-Bold, which only covers Latin-1. RTL (Arabic/Hebrew), CJK, or Cyrillic watermark text renders as tofu/missing glyphs or raises an encoding error — yet the field accepts up to 60 arbitrary characters.
    - ROTATED PAGES: the overlay is merged in unrotated page coordinates, so on pages with /Rotate 90/270 the 45-degree watermark appears at the wrong angle relative to the viewed orientation.
    - OFFSET/CROPPED MEDIABOX: the overlay is centered at mediabox width/2,height/2 and ignores a non-zero mediabox origin and any smaller CropBox, so on cropped or offset pages the watermark is mispositioned or partly off the visible area.
    - 0-page PDF: `len(reader.pages) or 1` avoids div-by-zero, but the loop never runs and an EMPTY (0-page) PDF is written with no error.
    - is_encrypted rejects owner-only-encrypted PDFs too (stricter than needed) — a merely permission-restricted PDF you can open is refused.
    - alpha=0.30 transparency is ignored by some older/print viewers, showing a solid gray stamp.
- **Optimizations:**
    - Cache the overlay PdfReader keyed by (width,height): most documents have uniform page size, so a fresh reportlab canvas is currently built for every page unnecessarily.
    - Reuse a single BytesIO/canvas buffer instead of allocating per page.
- **Improvements:**
    - Register a Unicode TTF (e.g. a bundled DejaVu/Noto) so CJK/RTL/accented watermark text renders.
    - Apply the page's /Rotate to the overlay and use CropBox with the correct origin offset.
    - Error on a 0-page document; make font size, color, opacity, angle, and position (center vs tiled) configurable.
- **Broader support:**
    - Image/logo watermark, not just text.
    - First-page-only or page-range watermarking.
    - Tiled/repeated watermark across the page for stronger anti-copy coverage.

#### Extract text from PDF  ·  `pdf-extract-text`  ·  _verified-working_

- **Edge cases:**
    - CID-keyed fonts without a ToUnicode CMap yield garbage or empty text — the 'no text found' guard then misfires (reports scanned when the text layer merely can't be decoded).
    - RTL (Arabic/Hebrew) and complex-script text is extracted in visual order and can come out reversed or mis-ordered; multi-column/table layouts are interleaved into unreadable reading order.
    - Ligatures and hyphenated line-breaks are not normalized/dehyphenated.
    - is_encrypted rejects even owner-only-restricted PDFs the user can open.
    - A single page whose extract_text() raises aborts the whole job (no per-page try/except).
    - All page text is accumulated in a Python list and joined at the end — memory grows with document size for very large PDFs.
    - Output is <uuid>.txt (see filename cross-cutting).
- **Optimizations:**
    - Stream each page's text straight to the output file instead of building one large in-memory list then joining.
    - pypdf's pure-Python extraction is slow; pypdfium2 (already a dependency for pdf-to-images) extracts text much faster and often more accurately — consider it as the engine or a fallback.
- **Improvements:**
    - Wrap per-page extraction so one malformed page is skipped, not fatal.
    - Expose pypdf's layout-preserving extraction mode and an optional page-range param.
    - Try an empty-password open before rejecting owner-only-encrypted files; offer an OCR fallback (tesseract) for scanned PDFs instead of a hard error.
- **Broader support:**
    - Output structured JSON (per-page text + page numbers) or Markdown with page separators.
    - Table-aware extraction to CSV.
    - Language/encoding hint for better CID decoding.

#### PDF to Word  ·  `pdf-to-docx`  ·  _concern_

- **Edge cases:**
    - Converts ALL pages with no page-range option; a large PDF renders/reconstructs every page via PyMuPDF, risking the job timeout and high memory, with only static 0.2 progress shown.
    - Scanned/image-only PDFs 'succeed' producing a docx with pictures but NO editable text (no OCR); the helpful 'may be scanned' message only appears if pdf2docx throws, so silent low-value output is common.
    - Encrypted PDFs are not pre-checked; user-password files fail inside fitz and fall into the generic catch-all error.
    - Multi-column layouts, complex tables, footnotes, and rotated pages are frequently mis-reconstructed (inherent pdf2docx limitation).
    - PyMuPDF is AGPL (licensing exposure noted in the module docstring) — a distribution/compliance concern, not runtime.
- **Optimizations:**
    - Expose start/end/pages to pdf2docx to convert only the needed range.
    - Enable pdf2docx multi_processing for large documents to use available CPU cores (worker is CPU-only but multi-core).
- **Improvements:**
    - Pre-detect encryption and scanned/no-text-layer state to give specific guidance (unlock / run OCR first) instead of one generic failure.
    - Provide per-page progress using pdf2docx's page loop rather than a static 0.2->1.0.
    - Add an OCR path for scanned inputs so the docx has real text.
- **Broader support:**
    - Page-range parameter.
    - ODT / RTF output options.
    - Table-only extraction mode for data-heavy PDFs.

#### PDF to images  ·  `pdf-to-images`  ·  _concern_

- **Edge cases:**
    - JPEG BLACK BACKGROUND: for JPEG output, `pil.convert('RGB')` on an RGBA bitmap merely drops the alpha channel without compositing, so transparent regions of a PDF become BLACK (whatever RGB was stored) instead of white. Should paste onto a white background first.
    - MEMORY BLOWUP AT HIGH DPI: dpi is capped at 600 but PAGE DIMENSIONS are not; a large-format page (A0 poster, engineering drawing) at 600 dpi produces a multi-hundred-megapixel bitmap that can OOM the worker. Cap total output pixels, not just dpi.
    - Password-protected PDFs fail at PdfDocument() -> generic error, even though pypdfium2 accepts a password argument.
    - Interactive FORM FIELD VALUES may not render because forms are not initialized (init_forms); filled form data can be missing from the image even though static annotations render.
    - JPEG quality is left at Pillow's default (75) — visibly soft output — and is not configurable.
    - Many-page documents create one temp file per page then a ZIP_DEFLATE archive of already-compressed images (wasted CPU + double I/O).
- **Optimizations:**
    - Render into BytesIO and write directly into the zip with ZIP_STORED, skipping per-page temp files and pointless DEFLATE on PNG/JPEG.
    - Explicitly close/free each pdfium bitmap after to_pil() to bound peak memory across pages.
    - Offer a grayscale/1-bit render option for text scans to cut size dramatically.
- **Improvements:**
    - Composite RGBA onto white before JPEG conversion; expose a JPEG-quality param and a background-color param.
    - Add a draw-annotations/forms toggle (with form init) and a page-range selector.
    - Guard total pixels = (width*scale)*(height*scale) and fail with a clear message before allocating.
- **Broader support:**
    - WebP/TIFF output formats.
    - Password parameter for encrypted inputs.
    - Single tall combined image (contact sheet / vertical strip) option.

#### Images to PDF  ·  `images-to-pdf`  ·  _concern_

- **Edge cases:**
    - MISLEADING 'LOSSLESS': the docstring says 'img2pdf, lossless' but the code re-encodes EVERY input to JPEG quality 90 before handing to img2pdf. Clean PNGs, screenshots, and line art are degraded with JPEG artifacts; text screenshots get ringing. img2pdf's actual lossless path (embedding original JPEG/PNG bytes) is bypassed.
    - EXIF ORIENTATION IGNORED: phone photos tagged with an EXIF rotation are saved without applying it, so portrait photos come out sideways. Needs ImageOps.exif_transpose().
    - DPI DROPPED: Pillow re-saves without a dpi argument, so img2pdf loses the original image DPI and sizes pages by pixel count at a default DPI — physical page size ends up wrong for scanned/print images.
    - CMYK, 16-bit ('I;16'), and 'F'/'I' mode images fall into the else branch and convert('RGB') can shift colors (CMYK) or clip/raise (16-bit TIFF).
    - MULTI-FRAME INPUTS lose data: animated GIF/WebP and multi-page TIFF only contribute their FIRST frame/page.
    - Category is 'images' (not 'pdf'); fine, but note it won't appear under the pdf group in listings.
- **Optimizations:**
    - For inputs that are already JPEG with no alpha, pass the original file straight to img2pdf (true lossless, no re-encode) instead of round-tripping through Pillow.
    - Feed img2pdf image bytes directly rather than writing temp .jpg files to workdir.
- **Improvements:**
    - Apply EXIF orientation and preserve/set DPI so pages are correctly sized and rotated.
    - Offer a lossless mode (embed PNG) vs compressed mode (choose JPEG quality); fix the docstring to match actual behavior.
    - Handle CMYK via an ICC-aware conversion and support 16-bit downsampling explicitly.
- **Broader support:**
    - Page-size normalization (fit each image to A4/Letter) with margin and orientation options.
    - Explode multi-frame GIF/WebP and multi-page TIFF into multiple pages.
    - Per-image ordering/rotation controls beyond strict upload order.

#### PDF to Markdown  ·  `pdf-to-markdown`  ·  _concern_

- **Edge cases:**
    - RUNTIME MODEL DOWNLOAD: 'first run downloads models' — on an air-gapped / offline WSL box the download fails and every conversion returns the generic 'could not convert'. Models should be baked in at build time.
    - Docling layout models on CPU are SLOW; a large PDF easily exceeds the job timeout, and progress is a static 0.3->1.0 so it looks hung.
    - DocumentConverter() is re-instantiated on EVERY job, reloading/initializing the pipeline each time (no model reuse) — a large per-job startup cost.
    - Encrypted PDFs fail into the generic catch-all with no specific 'unlock first' guidance.
    - Accepts .docx/.pptx/.html/.htm despite the 'pdf-to-markdown' slug; HTML with remote images/CSS won't fetch them (local-only).
    - No page limit; very large or scanned documents (if OCR is engaged) can be extremely slow and memory heavy.
- **Optimizations:**
    - Hold a module-level singleton DocumentConverter so a warm worker reuses loaded models across jobs instead of re-initializing per job.
    - Pre-download/bake Docling models into the image (and set offline env) to remove the runtime download and speed cold start.
    - Disable OCR when a text layer is present, and cap the thread count to avoid oversubscription on the shared worker.
- **Improvements:**
    - Distinguish 'model download/network failure' from 'conversion failure' in the error message.
    - Expose OCR on/off and a page-range parameter.
    - Emit extracted images/tables as sidecar assets referenced from the Markdown.
- **Broader support:**
    - Offer Docling's HTML/JSON export in addition to Markdown.
    - Accept image inputs (via OCR) and spreadsheets.
    - Configurable table-to-Markdown vs table-to-HTML rendering.


### Image tools

**Cross-cutting for this group:**

- No decompression-bomb / pixel guard on any PIL tool (convert, optimize, ico). All rely on Pillow's default MAX_IMAGE_PIXELS (~89 MP): a valid-but-large image raises DecompressionBombError which is swallowed by the broad `except Exception -> ToolError('the file is not a readable image')`, misreporting a legit large image as corrupt. Worse, within the 512 MB upload cap a small highly-compressed PNG or an uncompressed BMP/TIFF can decode to multi-GB RAM and OOM the CPU-only worker (killed -> generic 'internal error'). Set an explicit pixel cap and emit a clear 'image too large' message instead.
- EXIF orientation is ignored everywhere (convert, optimize, ico, upscale, caption). Phone photos carry an Orientation tag; since metadata is stripped by default, the pixels are never transposed, so portrait shots come out sideways/upside-down after conversion or optimization. A single `ImageOps.exif_transpose(img)` before save/inference would fix all of them.
- The `accepts` gate matches only the claimed filename suffix (jobs.py `_matched_extension`), not sniffed content — only archives get a mime cross-check. So a .txt renamed .png reaches the tool and dies at runtime with a generic ToolError (job error) instead of a clean 422 at submit; conversely valid image bytes with a wrong extension are rejected up front. Consider a light content sniff (magic/PIL verify) for image tools mirroring the archive mime check.
- Runtime model downloads contradict the offline/self-hosted posture: rembg `new_session` pulls U^2-Net weights from the internet on first use, and image-upscale `urlretrieve`s RealESRGAN_x4plus.pth from GitHub. On an air-gapped box both fail and are reported as 'background removal failed - the image may be unsupported' / 'could not download', masking the real cause. Pre-bundle weights in the image and treat missing-weights vs bad-image as distinct errors.
- Model/engine reuse is inconsistent: image-to-text caches its RapidOCR engine in a module global (good), but image-remove-bg builds a fresh rembg session every job and image-upscale reloads the .pth and re-.cuda()s every job. On the heavy queue this repeats expensive ONNX/torch init per request. Standardize a per-worker per-model cache (dict keyed by model name) across all AI image tools.
- Animated / multi-frame inputs are silently reduced to frame 0 across convert, optimize, ico, and caption (animated GIF, animated WebP, multipage TIFF). PIL opens only the first frame and none of these pass `save_all=True`, so animation/pages are dropped with no warning. Either preserve (save_all) or state single-frame explicitly in the description.
- Mode handling (CMYK / 16-bit / grayscale) is inconsistent and buggy: image-convert never forces RGB, so CMYK or I;16 -> PNG/WebP raises OSError -> 'could not encode'; image-optimize force-converts even mode L to RGB, needlessly tripling grayscale JPEG size. A shared normalize-mode helper (CMYK->RGB via ICC, I;16 downcast, keep L) would make all Pillow tools robust.
- Broad `except Exception -> ToolError(<one generic message>)` in remove-bg, convert, optimize, ico, and ocr collapses OOM, network-download failure, unsupported pixel mode, and timeout into a single unhelpful message, making support/debugging hard. Catch and label the common failure classes distinctly.

#### Image convert / resize  ·  `image-convert`  ·  _verified-working_

- **Edge cases:**
    - Animated GIF or animated WebP input -> only frame 0 is written (no save_all); animation is silently lost. Multipage TIFF likewise loses all pages but the first.
    - CMYK JPEG -> PNG/WebP/BMP/TIFF: CMYK is not in the flatten set and not 'P', so it is passed straight to save; PNG/WebP reject CMYK -> OSError -> 'could not encode the image as <fmt>' (JPEG target happens to work but may look color-inverted for Adobe CMYK).
    - 16-bit TIFF (mode I;16 / I) -> JPEG/WebP/AVIF fails ('could not encode') because those encoders need L/RGB; only PNG/TIFF preserve 16-bit.
    - EXIF Orientation not applied: a rotated phone photo converted to PNG (metadata stripped) comes out sideways.
    - Very tall/thin images are unconstrained — max_width only limits width, no max_height, so a 1x100000 image passes through at full height.
    - strip_metadata=False on a PNG/BMP target may pass an `exif=`/`icc_profile=` kwarg the encoder ignores or (older Pillow) rejects.
    - TIFF/BMP outputs are written uncompressed (no `compression=` for TIFF), so a large image yields a huge file.
    - Palette GIF with index transparency -> JPEG flatten path uses rgba.split()[-1] as mask which works, but semi-transparent edges get hard white fringing.
- **Optimizations:**
    - For JPEG sources being downscaled, call `img.draft('RGB', target_size)` before load — DCT-scale decode is dramatically faster and lighter than full decode + LANCZOS resize.
    - Use `img.thumbnail((mw, big))` instead of decode-then-resize to cap memory, and set an explicit MAX_IMAGE_PIXELS guard to avoid decoding bombs.
    - Pass `optimize=True`/`compress_level` for PNG and `method`/`lossless` for WebP so 'convert to png/webp' isn't left at default (larger) settings.
    - Add `compression='tiff_lzw'` for TIFF and note BMP is inherently uncompressed.
- **Improvements:**
    - Apply ImageOps.exif_transpose before saving so orientation survives metadata stripping.
    - Normalize CMYK/16-bit/exotic modes to RGB (via ImageCms for CMYK) before lossy save, with a clear message instead of 'could not encode'.
    - Distinguish 'image too large' (DecompressionBomb/OOM) from 'not a readable image' in the open/load except block.
    - Expose the flatten background color (currently hardcoded white) and a lossless-WebP toggle.
- **Broader support:**
    - save_all=True to preserve animated GIF/WebP and multipage TIFF.
    - Add max_height / exact WxH / percentage-scale and optional upscaling.
    - HEIC/AVIF/JXL as output targets (pillow-heif can encode HEIC), and SVG/PDF-page/ICO as inputs (rasterize).
    - Expose subsampling/progressive/chroma options for JPEG.

#### Remove background  ·  `image-remove-bg`  ·  _verified-working_

- **Edge cases:**
    - First use of a model triggers an internet download inside `new_session`; on an offline/self-hosted box this raises and is reported as 'background removal failed - the image may be unsupported', hiding the real (network) cause. Each of the 4 selectable models (u2net, isnet-general-use, u2netp, silueta) is a separate download.
    - `new_session(model)` is created fresh every job — no caching — so ONNX init cost is paid per request on the heavy queue.
    - Concurrent jobs with the same model each build their own session and (first run) race the same download with no lock -> duplicated memory / partial-file risk.
    - src.read_bytes() loads the whole file into RAM and rembg then re-decodes it — double memory; the alpha composite runs at full input resolution, so large photos are slow and memory-heavy on CPU with no size cap.
    - Animated WebP input (accepted) -> only the first frame is matted.
    - CMYK/16-bit inputs decoded by rembg's internal PIL step may fail -> same generic message.
    - Broad except also swallows onnxruntime provider errors and OOM into 'unsupported image'.
- **Optimizations:**
    - Cache sessions in a module-level dict keyed by model name (as image-to-text does for its engine) to skip per-job ONNX init.
    - Pre-bundle the U^2-Net/isnet weights in the image so no runtime download is needed.
    - Downscale very large inputs before inference (U^2-Net infers at 320x320 anyway) and only composite the mask back at full res, reducing peak memory.
    - Explicitly select CPUExecutionProvider to avoid onnxruntime probing/ warning for a missing CUDA provider.
- **Improvements:**
    - Separate 'model download/network failed' from 'unsupported image' in the error path.
    - Expose alpha-matting parameters (foreground/background threshold, erode size) for cleaner hair/edges.
    - Add an option to composite the cutout onto a chosen solid color instead of transparency.
    - Provide real progress rather than a single 0.3 -> 1.0 jump.
- **Broader support:**
    - Offer additional models (birefnet, isnet-anime, SAM-based).
    - Option to also emit the raw alpha mask alongside the cutout.
    - Accept HEIC (register pillow_heif here) and add .heic to accepts.

#### Optimize image  ·  `image-optimize`  ·  _verified-working_

- **Edge cases:**
    - Output can be LARGER than input: BMP/TIFF/HEIC and many already-compressed PNGs re-encode to a bigger PNG; the pct formula `int((1-after/before)*100)` then reports a negative ('-120% smaller') and the bloated file is still written. No keep-smaller-of-two logic.
    - Description says 'keeps the same format' but HEIC/TIFF/BMP are all forced to PNG — misleading, and HEIC->PNG is a huge size regression.
    - EXIF orientation lost: JPEG path converts to RGB and passes no exif, so oriented photos are rotated and all metadata is stripped unconditionally (undocumented).
    - Grayscale JPEG (mode L) is force-converted to RGB, tripling channel count and enlarging the 'optimized' output.
    - CMYK JPEG -> convert('RGB') without ICC shifts colors and drops the color profile.
    - `quality` param is exposed in the schema but silently ignored on the PNG branch (PNG/TIFF/BMP/HEIC inputs), so users setting quality see no effect.
    - A lossless WebP source is re-encoded lossy at quality 75, silently degrading it.
    - Animated WebP -> only the first frame is re-encoded (animation dropped).
- **Optimizations:**
    - Compare sizes and, if the re-encode is larger, copy the original bytes instead so 'optimize' never inflates.
    - Run PNG output through palette quantization (pngquant/oxipng-style) or Pillow quantize for non-photographic images — plain `optimize=True` only does zlib and saves little.
    - Use img.draft for JPEG decode, and expose/tune JPEG subsampling for real size wins.
    - Keep mode L for grayscale instead of promoting to RGB.
- **Improvements:**
    - Preserve EXIF orientation (transpose) even while stripping other metadata.
    - Either actually keep the source format (write HEIC/TIFF back) or fix the description.
    - Add a target-filesize mode that binary-searches quality to hit a byte budget.
    - Expose lossless and strip-metadata toggles.
- **Broader support:**
    - Allow HEIC/AVIF output (far smaller than the current PNG fallback).
    - Support GIF optimization (frame dedup / palette).
    - Support optional format conversion within the optimize step.

#### Image to icon (.ico)  ·  `image-to-ico`  ·  _verified-working_

- **Edge cases:**
    - Non-square source is squished: all target sizes are square (16..256) and the image is resized to square with no center-crop/pad, so a 1000x500 logo becomes a distorted favicon.
    - Source smaller than a requested size: depending on Pillow version those sizes are either upscaled (blurry) or dropped; a source under 16x16 can yield an ICO with a single/zero real entry that still passes the `st_size==0` check.
    - Animated GIF/WebP or multipage TIFF -> only frame 0 is used.
    - Very large source is fully decoded before the 256px cap, so a huge upload still costs full-image RAM (no pixel guard).
    - Fixed size set [16,32,48,64,128,256] is not user-selectable — no 24x24, and no way to request 256-only.
- **Optimizations:**
    - Pre-thumbnail the source to 256x256 once and generate the smaller sizes from that base to cut per-size resize cost.
    - Set an explicit resampling filter (LANCZOS) for crisp small icons and add a MAX_IMAGE_PIXELS guard.
- **Improvements:**
    - Center-crop or pad to square before generating sizes to avoid aspect distortion.
    - Detect and clearly handle sources smaller than the smallest icon size (upscale intentionally or error with a specific message).
    - Let the user choose which sizes to include.
    - Validate that at least one image entry was actually written, not just that the file is non-empty.
- **Broader support:**
    - .icns (macOS) and platform icon sets (Android mipmaps, apple-touch-icon PNG set).
    - Accept SVG input for crisp vector-sourced icons.
    - Build an ICO from multiple uploaded images (one per size).

#### Describe image (AI)  ·  `image-caption`  ·  _verified-working_

- **Edge cases:**
    - The full image is base64-encoded into a single JSON POST with no downscaling: a large (up to 512 MB) upload becomes a ~683 MB base64 body -> huge memory and likely Ollama rejection; moondream only needs a small image.
    - available() checks any model whose name startswith 'moondream', but generate() sends the bare tag 'moondream'. If only 'moondream:v2' is pulled, availability passes yet generate returns an error -> 'the vision model returned an error'. Availability and request tags can disagree.
    - BMP and TIFF are in accepts but Ollama's Go image decoder may not handle them -> 'vision model returned an error' with no hint it's a format issue.
    - Animated GIF (accepted) -> model sees only the first frame or errors.
    - No max-token cap (num_predict) or temperature: output can be long/slow and is non-deterministic.
    - A corrupt-but-.jpg-named file is sent straight to Ollama (no PIL pre-validation) -> opaque model error.
    - Concurrency: moondream + qwen2.5:3b both resident in Ollama on CPU can thrash/OOM under simultaneous heavy jobs (model load churn).
- **Optimizations:**
    - Downscale/re-encode to a small RGB JPEG (~768-1024 px) with PIL before base64 — cuts payload ~100x, speeds inference, and sidesteps BMP/TIFF/GIF decode issues.
    - Set `keep_alive` so the vision model stays warm between jobs.
    - Set `options.num_predict` to bound output length and latency.
- **Improvements:**
    - Call generate() with the exact resolved tag returned by /api/tags instead of the bare 'moondream', eliminating the availability/request mismatch.
    - Pre-open with PIL and convert to a known-good format so 'not an image' is caught locally with a clear message.
    - Distinguish connect-timeout vs read-timeout vs HTTP 500 in the error text.
    - Expose temperature/seed for reproducibility.
- **Broader support:**
    - Multiple images per request and structured (JSON) output modes.
    - Selectable vision model (llava, qwen2-vl, moondream) as a param.
    - HEIC input (convert first).

#### Upscale image (AI)  ·  `image-upscale`  ·  _gpu-gated_

- **Edge cases:**
    - Single whole-image forward pass with no tiling: at 4x, a mid-size photo (e.g. 3000x2000) blows up VRAM and CUDA-OOMs, surfacing as the worker's generic 'internal error'. Real-ESRGAN normally tiles.
    - Alpha is discarded: `.convert('RGB')` drops the alpha channel, so a transparent PNG loses transparency.
    - _CACHE is hardcoded to /root/.cache/selfx, assuming the worker runs as root — a non-root worker fails mkdir/download; the path also ignores settings.data_dir.
    - Weights are downloaded from GitHub at first run -> fails on air-gapped hosts ('could not download the upscaling model weights').
    - Model is reloaded and re-.cuda()'d every job (no cache) — full weight load per request.
    - Fixed 4x only: a 2000x2000 input becomes an 8000x8000 PNG (16x pixels), large in VRAM, RAM, and on disk, with no x2 option.
    - No GPU lock: two concurrent heavy jobs both grab CUDA and OOM.
    - Loading a .pth via torch/spandrel is an unpickle — supply-chain/code-exec exposure if the pinned URL/weights are tampered with.
- **Optimizations:**
    - Cache the loaded model in a module global per worker and reuse across jobs.
    - Tiled inference (with overlap) to bound VRAM independent of input size.
    - Use fp16/autocast to roughly halve VRAM and speed up.
    - Use torch.inference_mode() and free the input tensor promptly.
- **Improvements:**
    - Preserve alpha (upscale RGB and the alpha plane separately, then recombine).
    - Derive the cache dir from settings.data_dir and don't assume root; pre-bundle weights offline.
    - Map CUDA-OOM and download failures to friendly, specific messages.
    - Offer an output-format/quality choice so the 4x result isn't always a giant PNG.
- **Broader support:**
    - Selectable scale (x2/x4) and model (photo/anime), optional face enhancement (GFPGAN) and denoise strength.
    - Optional slow CPU fallback (with a warning) so the tool isn't fully GPU-gated.

#### Image to text (OCR)  ·  `image-to-text`  ·  _verified-working_

- **Edge cases:**
    - Default RapidOCR models are Chinese+English only: Japanese/Korean/Arabic/Hebrew/Cyrillic/Thai/Devanagari are not recognized and yield 'no text was detected'. RTL scripts would also be mis-ordered even if detected.
    - Reading order is detection order, not layout order: multi-column documents and tables get lines interleaved/jumbled; horizontally separated boxes are joined with newlines and lose inter-box spacing.
    - Confidence (row[2]) is discarded, so low-confidence garbage is included with no threshold.
    - Some accepted formats may not decode depending on the opencv build used by RapidOCR (WebP/TIFF support is build-dependent; multipage TIFF -> first page only).
    - Very large images make detection slow/memory-heavy with no downscale cap.
    - 90-degree/vertical text may still fail even with the angle classifier.
    - Lazy _ENGINE init is unlocked — two first-run jobs in one process could both construct RapidOCR (double model load), though it converges.
- **Optimizations:**
    - Engine is already cached module-global (good); additionally set onnxruntime intra-op thread count to use the CPU sensibly and avoid oversubscription across concurrent workers.
    - Downscale oversized images before detection.
    - Allow disabling the angle classifier for clean born-digital scans to speed up.
- **Improvements:**
    - Sort detected boxes into reading order (top-to-bottom, left-to-right, with simple column detection) and preserve spacing.
    - Add a confidence threshold param and optionally emit confidence/bounding boxes.
    - Expose a language/model selection param.
    - Guard the lazy engine init with a lock.
- **Broader support:**
    - Add language packs (japan, korean, latin, cyrillic, arabic, devanagari).
    - Accept PDF input and OCR per page (multi-page text).
    - Output formats beyond plain text: JSON with coordinates, hOCR, TSV, or a searchable PDF.


### Document tools

**Cross-cutting for this group:**

- Inconsistent availability preflight: office/html/ebook implement available() for a clean 409, but pandoc-convert and ocr-pdf do NOT -> missing-binary jobs are accepted then fail at run_cmd. Standardize an available() on every adapter.
- Enum/option assumptions are tied to the Docker image's bundled deps (Gotenberg for landscape, tesseract eng/deu/fra/spa) but the actual deployment is WSL-no-Docker: landscape (Gotenberg-only) and deu/fra/spa OCR silently degrade or fail there.
- In-process libraries bypass run_cmd's timeout — only subprocess tools are time-bounded. WeasyPrint (html-to-pdf) can hang the worker indefinitely; a worker-level watchdog/subprocess wrapper is needed for all in-process converters.
- Format detection trusts the filename suffix end-to-end: the extension gate matches orig_name, the uuid stored file carries that lowercased suffix, and each converter autodetects from it. A mislabeled file or a dotfile-only name ('.docx' -> empty stored suffix) reaches the wrong/undetectable converter. Only ARCHIVE_MIMES enforces a content/MIME cross-check; document formats get none.
- Progress is cosmetic across all five tools (fixed 0.2-0.4 then 1.0). Long OCR/ebook/office jobs give no real feedback even though the underlying CLIs emit per-page/percent progress that could be parsed.
- SSRF / local-file exposure during conversion: WeasyPrint (file:// + http) and, more mildly, pandoc LaTeX \input can read local files. Add sandboxing (WeasyPrint url_fetcher allowlist, pandoc --sandbox).
- No per-job output-size cap: small inputs can yield huge outputs (multi-sheet xlsx->PDF, OCR PDF/A bloat, ebook image blow-up). Only global retention/disk accounting exists.
- Overlapping HTML->PDF paths (office-convert, pandoc[no pdf], html-to-pdf) use different engines with different fidelity and no guidance on which to choose; Markdown->PDF has no good path (office renders it literally, pandoc cannot emit PDF).

#### Office / HTML / Markdown to PDF  ·  `office-convert`  ·  _concern_

- **Edge cases:**
    - landscape=True is SILENTLY IGNORED on the local-LibreOffice path: _via_libreoffice(ctx, src, out_path) never receives or uses the param; only _via_gotenberg sets data={'landscape':'true'}. Since the real deployment is WSL-no-Docker (LibreOffice fallback per project memory), the Landscape option does nothing there.
    - available() TOCTOU: returns True if Gotenberg OR soffice present. If only Gotenberg was up at submit and it dies before run(), run() falls to _via_libreoffice which finds no soffice and raises 'no document-conversion backend is available' -> job fails with no fallback.
    - .md input: neither Gotenberg's LibreOffice route nor stock local LibreOffice reliably renders Markdown; older LO imports .md as literal plain text (raw '#','*' shown), so the 'Markdown to PDF' promise is poor fidelity.
    - CJK/RTL/complex-script docs render as tofu boxes or mis-shaped if Noto CJK/Arabic fonts aren't installed in WSL; LibreOffice substitutes fonts silently, no warning.
    - Password-protected .docx/.xlsx/.pptx: headless soffice cannot prompt; conversion fails with an opaque stderr tail rather than the friendly 'password-protected' message pdf_merge gives.
    - Very wide / multi-sheet .xlsx: LibreOffice prints every sheet with no fit-to-page/scaling control, so columns clip at the page edge and output can balloon to hundreds of pages.
    - Dotfile-only orig_name (e.g. '.docx'): passes the extension gate ('.docx'.endswith('.docx')) but safe_suffix() returns '' so the stored file has NO extension -> Gotenberg/LibreOffice cannot detect format and conversion fails.
    - 1-byte/structurally-empty office file (empty upload rejected earlier, but a tiny malformed .docx is not): LibreOffice can emit a valid blank 1-page PDF that passes the st_size==0 guard, so garbage input silently yields a blank PDF.
- **Optimizations:**
    - run() calls _gotenberg_ok() at line 61 in addition to the availability check at submit -> 2 HTTP health GETs per job; cache the probe with a short TTL or thread the decision through ToolContext.
    - LibreOffice cold-starts ~1-2s per job; a persistent soffice --headless UNO listener (unoserver) or keeping Gotenberg warm removes that per-job spawn cost for batch use.
    - The 'if produced != out_path' rename branch is dead on the LibreOffice path (both equal <stem>.pdf) — remove it.
    - For 512MB inputs stream to Gotenberg with a per-format timeout tighter than the blanket 600s instead of relying on httpx buffering.
- **Improvements:**
    - Honor landscape on the LibreOffice path via writer_pdf_Export FilterOptions / a page-style macro, or document that Landscape only works when Gotenberg backs it.
    - Expose which backend is active (Gotenberg vs LibreOffice) so the UI knows whether Landscape is actually honored.
    - Detect password-protected inputs up front and raise the same friendly message pdf_merge uses.
    - Guard against blank-output: sniff PDF page count / minimum size to catch a failed parse that produced an empty PDF.
    - Emit real progress by parsing soffice/Gotenberg output or page count instead of a fixed 0.3 then 1.0 jump.
- **Broader support:**
    - Expose page size (A4/Letter), margins, and fit-to-width for spreadsheets; PDF/A output option.
    - Accept .csv (with delimiter/encoding params), .odp, .odg, template formats.
    - Per-sheet or per-slide range selection for xlsx/pptx.
    - Font embedding/subsetting option.

#### Markup convert (Pandoc)  ·  `pandoc-convert`  ·  _verified-working_

- **Edge cases:**
    - No available() override (inherits base True) -> if pandoc is not installed the job is accepted then fails at run_cmd with 'required program pandoc is not installed', instead of a clean 409 preflight like office/html/ebook.
    - HTML output is a bare FRAGMENT: 'pandoc src -o out.html' without -s/--standalone emits no <html><head><meta charset> wrapper -> non-ASCII content can mojibake and there is no title; DOCX/EPUB/ODT are standalone but HTML/LaTeX are not.
    - Relative image refs in uploaded Markdown/HTML don't resolve: the single uuid-named file sits alone in uploads/, no sibling assets, --resource-path unset -> images silently dropped from docx/epub/odt.
    - required:['to'] makes the schema default 'html' decorative — a request omitting 'to' is rejected 422 (jsonschema.validate does not fill defaults), contradicting the 'default html' intent.
    - .tex (LaTeX) input with custom macros/packages or \input{...} parses poorly and can read local files via \input/\include.
    - .rst/.epub -> md round-trips silently lose tables and raw-HTML structure.
    - Converting to the same format (e.g. .html -> html) is allowed (unlike ebook_convert's same-format guard) -> wasteful no-op.
    - Pathological Markdown (giant tables/deep nesting) uses the blanket 1800s job_timeout with no lighter cap.
- **Optimizations:**
    - Add --sandbox (pandoc 3.2+) to block filesystem reads (security) and avoid resource I/O.
    - For HTML targets add --embed-resources --standalone only when a self-contained doc is wanted (correctness + inlines assets).
    - Set a tool-specific timeout shorter than 1800s so a stuck conversion doesn't hold a queue slot for 30 minutes.
- **Improvements:**
    - Add available() via shutil.which('pandoc') for a 409 preflight, matching the other document tools.
    - Pass -f/--from derived from the input extension instead of relying on pandoc autodetect (robust for .htm and ambiguous names).
    - Add --standalone plus --metadata title=<orig_name> for HTML/LaTeX targets so outputs are complete documents.
    - Surface pandoc stderr warnings (dropped images, unknown syntax) into the job message.
- **Broader support:**
    - Accept a zip asset bundle so images/CSS referenced by Markdown/HTML get embedded.
    - Expose offline targets pandoc supports: rst, rtf, txt, org, latex, json, gfm, plain.
    - TOC (--toc), section numbering, reference-doc template (docx/odt), and citations (--citeproc + uploaded .bib).
    - Input formats: .org, .textile, .ipynb, mediawiki.

#### HTML to PDF (WeasyPrint)  ·  `html-to-pdf`  ·  _concern_

- **Edge cases:**
    - SSRF / local-file read: HTML(filename=src) uses WeasyPrint's default url_fetcher which resolves file://, http(s):// and relative URLs. An uploaded HTML with <link href='file:///etc/passwd'>, <img src='file:///...'> or <img src='http://169.254.169.254/...'> is fetched and can be embedded/exfiltrated. The code's 'embedded remote resources are not fetched' claim is false and a successful fetch raises no exception, so it isn't caught.
    - No timeout: WeasyPrint runs IN-PROCESS (write_pdf), so run_cmd's timeout does not apply. A pathological doc (CSS that generates millions of pages, huge tables, deep nesting) blocks the worker until any RQ/job hard-timeout — can wedge the queue.
    - JavaScript is not executed: SPA/canvas/chart HTML renders blank or unstyled; users expecting browser-equivalent output are surprised.
    - Relative asset refs don't resolve: base_url is the uploads dir (lone uuid file, no siblings) so local style.css/logo.png are missing -> unstyled PDF, and WeasyPrint does not error.
    - Remote http(s) images/fonts on an offline WSL box hang until socket timeout, adding long latency with no run_cmd timeout to bound it.
    - Non-UTF8 HTML without <meta charset>/BOM is mis-decoded (mojibake).
    - Rare/unsupported CSS (some grid/flex gaps, position:sticky) silently degrades vs a browser.
    - No landscape/page-size param (office_convert has landscape; this tool has none) -> orientation only controllable by embedding @page CSS.
- **Optimizations:**
    - Provide a restrictive url_fetcher that blocks network + file:// (allow only data: URIs) — faster (no I/O stalls) and closes the SSRF/file-read hole.
    - Reuse a FontConfiguration and warm the Pango/fontconfig cache across jobs; the first render pays a large font-init cost.
    - Run WeasyPrint in a subprocess or watchdog thread so it gets a real wall-clock timeout and can't hang the worker.
- **Improvements:**
    - Wrap rendering with an explicit timeout/watchdog and a memory guard.
    - Fix the misleading error string; distinguish 'HTML parse error' from 'resource blocked'.
    - Add page-size/orientation/margin params (inject @page) to match office_convert.
    - Log WeasyPrint warnings (unresolved resources, unsupported CSS) into the job message.
- **Broader support:**
    - Accept a zip bundle (HTML+CSS+images+fonts), extract it, and set base_url to the extracted dir so real pages render with assets.
    - Opt-in 'allow remote' flag for trusted use; default to data:-only.
    - Markdown -> (HTML) -> PDF option to fill the Markdown->PDF gap left by pandoc/office.
    - Header/footer and page numbers via @page margin boxes exposed as params.

#### Convert ebook (Calibre)  ·  `ebook-convert`  ·  _verified-working_

- **Edge cases:**
    - DRM-protected input (Kindle AZW/AZW3, Adobe EPUB): Calibre can't decrypt; the generic 'may be DRM-protected' message fires, but Calibre may instead error mid-run with a raw stderr tail.
    - PDF as input (.pdf accepted): Calibre PDF->EPUB/MOBI reflow is notoriously garbled (columns/figures scrambled); users get low-quality output with no warning.
    - PDF as OUTPUT is fixed-layout and low quality (no reflow) — far worse than office-convert/html-to-pdf for the same target.
    - Same-format guard is string-based on the last suffix: '.azw' -> azw3 is allowed (different strings) despite being near-identical; multi-suffix names (x.tar.epub) compare only 'epub'.
    - Concurrency: runs share Calibre's config dir (~/.config/calibre) with no per-job CALIBRE_CONFIG_DIRECTORY (unlike office_convert's per-job LO profile) -> possible lock/plugin-cache contention under the tested 8-way concurrency.
    - Non-UTF8 .txt/.html input: Calibre guesses encoding; a wrong guess garbles text (no --input-encoding exposed).
    - Large or image-heavy EPUB->MOBI can exceed the 600s timeout on CPU-only WSL.
    - .txt -> epub relies on heuristic paragraph/chapter detection; poorly-formatted text yields one giant chapter or wrong breaks.
- **Optimizations:**
    - Set CALIBRE_CONFIG_DIRECTORY/HOME to a per-job dir to isolate state and avoid lock waits (speeds parallel jobs).
    - Expose a 'fast' path that disables some default heuristics (font-rescaling, structure detection) when not needed.
    - Adaptive timeout by input size instead of a flat 600s so a stuck job doesn't hold the heavy queue for 10 minutes.
- **Improvements:**
    - Expose --input-encoding, --title, --authors, --cover, --output-profile (e.g. kindle_pw3) for usable Kindle files.
    - Detect DRM explicitly from Calibre's exit/stderr signatures for a precise message instead of inferring from 'no output'.
    - Warn when PDF is the input or output that quality will be poor, or route PDF->text via a better path.
    - Parse Calibre's printed percentages into ctx.progress instead of a fixed 0.3.
- **Broader support:**
    - More outputs Calibre supports: pdb, lit, htmlz, rtf, lrf, snb; comic inputs .cbz/.cbr.
    - Metadata editing (series, tags, language) and cover injection.
    - Kindle device profiles and margin controls.

#### OCR (searchable PDF)  ·  `ocr-pdf`  ·  _concern_

- **Edge cases:**
    - No available() override -> if ocrmypdf/tesseract isn't installed the job is accepted then fails at run_cmd, instead of a 409 preflight (inconsistent with office/html/ebook).
    - Language packs: the enum offers eng/deu/fra/spa because the Dockerfile bundles them, but the REAL deployment is WSL-no-Docker (project memory) where only eng tesseract data may exist -> choosing deu/fra/spa fails at runtime with a raw tesseract error.
    - Password/encrypted PDF: no password param; ocrmypdf errors (needs qpdf decrypt) with an opaque stderr tail — no friendly 'password-protected' message.
    - Fully-digital PDF (text on every page): --skip-text skips OCR but Ghostscript still re-encodes to PDF/A (default output-type), bloating size and shifting colors for no benefit.
    - 10k-page or high-DPI scans: OCR is CPU-bound; with run_cmd defaulting to the 1800s job_timeout a large scan times out ('job exceeded the time limit').
    - Upside-down/rotated scans aren't corrected — deskew is exposed but --rotate-pages is not, so 90/180-degree pages OCR to garbage.
    - Low-DPI (<200) or image-only PDFs without DPI metadata: poor accuracy, and ocrmypdf may refuse ('image has no resolution'); no --image-dpi/--oversample exposed.
    - RTL/CJK scans (Arabic/Hebrew/Chinese/Japanese) aren't in the language enum at all.
    - Mixed-language pages: only a single language selectable, though tesseract supports eng+fra style combos.
- **Optimizations:**
    - Default --output-type pdf (instead of the implicit pdfa) to skip the Ghostscript PDF/A pass -> much faster, no color shift; make PDF/A opt-in.
    - Set --jobs N to available CPUs (ocrmypdf parallelizes per page) and --optimize 1 to shrink output.
    - Add --tesseract-timeout per page to bound pathological pages instead of failing the whole job on the global timeout; consider --fast-web-view.
    - Short-circuit a fully-text PDF to a copy instead of round-tripping through Ghostscript.
- **Improvements:**
    - Add available() probing ocrmypdf + 'tesseract --list-langs' so the enum reflects installed packs and yields a 409 when missing.
    - Add a page-count-tuned per-job timeout and parse ocrmypdf's per-page progress into ctx.progress.
    - Detect encrypted input and emit a friendly message; optionally accept a password param.
    - Expose --rotate-pages (auto-orient) and --clean (unpaper) alongside deskew.
- **Broader support:**
    - Multi-language selection (eng+deu) and more packs (ara, heb, chi_sim, jpn, rus) when installed.
    - Modes: --redo-ocr / --force-ocr to re-OCR bad existing text.
    - Sidecar text output (--sidecar), PDF/A level choice, --optimize level.
    - Accept image inputs (png/tiff/jpg) by wrapping into a PDF first (ocrmypdf --image-dpi / img2pdf).


### Media / audio / video tools

**Cross-cutting for this group:**

- Output filenames are derived from the UUID-named input (src.stem is a UUID), so every media tool except media-download emits files like '<uuid>-clip.mp4' / '<uuid>-thumb.jpg' / '<uuid>_(Vocals)_...mp3'. Unless the download route remaps to the stored orig_name, users download uuid-gibberish filenames. media-download is the exception (keeps yt-dlp's restrictfilenames title).
- String time params (start/time in trim, thumbnail, gif) are only maxLength-validated (12 chars); arbitrary content is passed straight to ffmpeg -ss/-t. shell=False prevents injection, but malformed values produce opaque ffmpeg errors surfaced as generic 'check the start time' messages. A shared time-format validator (accept int seconds or HH:MM:SS[.ms]) would give precise, early errors across all four tools.
- accepts lists are inconsistent across the media group: media-convert accepts .wma/.aiff/.mpeg/.mpg/.3gp; audio-extract and audio-normalize and video tools each accept different subsets. A file usable in one media tool is rejected by a sibling for no functional reason. Normalize accepts .wma/.aiff outputs it can't encode well.
- The file gate only checks the filename extension (archives additionally get MIME sniffing). Mislabeled media (a .mp4 that is actually text, a .wav that is actually mp3) passes validation and fails deep inside ffmpeg with a generic stderr tail rather than a clean early rejection.
- Three tools run heavy work in-process and therefore bypass run_cmd's 1800s timeout, relying solely on the RQ worker timeout: speech-denoise (noisereduce), voice-isolation (audio-separator), and media-download (yt-dlp). The ffmpeg-based tools are covered by run_cmd's default 1800s, except media-convert which uses its own deadline that only fires on progress-line arrival.
- No tool enforces an output size or free-disk guard. Only uploads are capped (max_upload_mb=512). media-convert's gif preset, gif-from-video at max params, media-download (no max_filesize), and speech-denoise can each produce very large outputs or exhaust disk.
- This is a CPU-only box, but several defaults are not tuned for it: media-convert webm-vp9 uses libvpx defaults (extremely slow, and no -crf when omitted), voice-isolation runs MDX on onnxruntime-CPU, and speech-denoise uses single-threaded noisereduce — all realistic 1800s-timeout candidates on non-trivial inputs.
- Lossy tools (audio-extract same-codec, audio-normalize, speech-denoise audio output) re-encode with ffmpeg default bitrate/codec, silently downgrading e.g. a 320 kbps mp3 to ~128 kbps. A copy-when-codec-matches fast path and explicit bitrate carry-over would preserve quality and speed things up.
- Only media-convert streams -progress for a live bar; the other ffmpeg tools set a static 0.3/0.4 then jump to 1.0, and the in-process tools never report intermediate progress — poor UX on multi-minute media jobs.

#### Audio / Video convert  ·  `media-convert`  ·  _concern_

- **Edge cases:**
    - gif preset has NO -t/duration cap (unlike gif-from-video which caps at 60s): converting a 2-hour source to 'gif' feeds the entire timeline through palettegen/paletteuse -> multi-GB output and huge memory, easily fills disk or hits the 1800s timeout
    - proc.wait(timeout=30) after stdout EOF is a hardcoded 30s unrelated to job_timeout: a legitimately slow finalize/mux of a large mp4/webm on slow disk takes >30s -> TimeoutExpired -> caught by generic except -> _kill + 'the conversion process failed unexpectedly' on an otherwise-successful encode
    - manual deadline is only checked inside `for line in proc.stdout` (i.e. when a progress line arrives). If ffmpeg stalls during input analysis of a pathological/corrupt file before emitting any -progress line, the read blocks with no deadline enforcement until the RQ worker kills it
    - webm-vp9 fragment sets `-b:v 0` but appends `-crf` only when the crf param is supplied; with no crf, libvpx-vp9 runs `-b:v 0` alone (no target, no quality) -> undefined/very poor quality output, a known VP9 CQ-mode gotcha
    - audio-only input + a video preset (mp4-h264/webm-vp9): libx264/libvpx get no video stream -> ffmpeg 'Output file does not contain any stream' surfaced only as opaque stderr tail; presets are not filtered by input media type
    - video-with-no-audio + an audio preset (mp3/opus/wav/flac uses `-vn`): fine, but a video with no audio + mp4-h264 maps no audio silently; conversely mp3 on a silent video errors
    - ffprobe format=duration returns 'N/A' for some streams/images -> float() raises -> _duration returns 0.0 -> progress bar frozen at 0.02 until 'end'
    - crf param is silently ignored for mp3/opus/wav/flac/gif presets: user moves a 'Quality (CRF)' slider with zero effect and no warning
    - no `-map`: extra audio tracks, all subtitle tracks, and chapters are dropped; multi-language sources lose everything but the default streams
    - out_time_us parsing uses int(value); early 'N/A' values are caught, but very large durations near 2^63 us are not a concern in practice
- **Optimizations:**
    - webm-vp9 on this CPU-only box uses libvpx defaults (deadline=good, cpu-used=0) which is brutally slow — a few-minute 1080p clip can exceed 1800s; add `-cpu-used 4 -deadline good -tile-columns` for realistic throughput
    - add a stream-copy fast path (`-c:v copy -c:a copy`) when the requested container/codec already matches the input (e.g. remux-only) to avoid a full re-encode
    - libx264 preset is hardcoded 'medium'; expose or lower to 'veryfast'/'faster' for CPU-bound throughput on long inputs
    - gif preset re-runs a full 2-pass palette every time; for large sources cap frames via fps+scale earlier in the graph and add a hard -t budget
- **Improvements:**
    - replace the magic `proc.wait(timeout=30)` with a value derived from remaining time until `deadline` so slow finalizes of large outputs are not falsely killed
    - add an idle/no-progress watchdog so a stalled ffmpeg (no stdout for N seconds) is killed even before the first progress line
    - for webm-vp9, always inject a default `-crf 32` when the user omits crf, so quality is defined rather than `-b:v 0` alone
    - validate input has the stream type the chosen preset needs (probe for video/audio) and fail with a clear message instead of a raw ffmpeg tail
- **Broader support:**
    - container/codec presets beyond the fixed 7 (e.g. hevc/av1, mkv passthrough, alac, m4a-aac)
    - expose resolution/scale, fps, audio bitrate, and channel-downmix params
    - subtitle/second-audio-track preservation via -map
    - two-pass or target-filesize mode for bitrate-constrained delivery

#### Extract audio  ·  `audio-extract`  ·  _verified-working_

- **Edge cases:**
    - same-codec extraction always re-encodes: input .mp3 -> format=mp3 runs libmp3lame at `-q:a 2` (lossy re-encode of already-lossy audio); aac from an .m4a re-encodes aac->aac instead of copying -> avoidable generational quality loss
    - wav output is hardcoded pcm_s16le: a 24-bit/32-bit float source is silently truncated to 16-bit (quality loss), and there is no way to preserve original bit depth
    - no `-map a:0?`: only the default audio track is extracted; multi-language / commentary tracks are silently dropped
    - video/file with no audio stream -> ffmpeg produces no/empty output -> handled as 'no audio track found', good, but the ffmpeg exit is nonzero so the message comes from the empty-file check not a clean detection
    - accepts list is narrower than media-convert (no .wma, .aiff, .mpeg/.mpg, .3gp): a .wma/.aiff the user can normalize or convert is rejected here for no real reason
    - fixed progress 0.3 -> 1.0 with run_cmd blocking: a 2-hour extraction shows no movement for minutes
- **Optimizations:**
    - add `-c:a copy` when the source audio codec already matches the requested container (mp3->mp3, aac in mp4->aac/.m4a, flac->flac) to make extraction near-instant and lossless
    - stream the ffmpeg `-progress pipe:1` output (as media-convert does) for a live progress bar instead of the static 0.3
    - use `-vn -sn -dn` to skip video/subtitle/data demux work explicitly on container inputs
- **Improvements:**
    - expose bitrate/quality (currently mp3 fixed q2, aac 192k, opus 128k) so users can trade size vs quality
    - detect codec==container match and switch to copy automatically, surfacing 'copied without re-encoding' in the status message
    - wrap 'file has no audio' as an explicit up-front probe rather than inferring from an empty output
- **Broader support:**
    - track-selection param for multi-audio sources
    - bit-depth/sample-rate/channel (mono downmix) params
    - align accepts with media-convert (.wma, .aiff, .mpeg, .3gp, .opus)
    - alac / m4a container output

#### Normalize audio  ·  `audio-normalize`  ·  _concern_

- **Edge cases:**
    - single-pass `loudnorm` is used (I=-16:TP=-1.5:LRA=11) — this is the less-accurate dynamic mode; true EBU-R128 targeting needs a 2-pass measure-then-apply, so the achieved integrated loudness can drift several LU from the -16 target
    - loudnorm upsamples internally and, with no trailing `-ar`/aresample, the OUTPUT sample rate becomes 192 kHz for many inputs — a 44.1 kHz mp3 normalizes to a 192 kHz file, bloating size and possibly breaking downstream players
    - no explicit `-c:a`/bitrate on output: a 320 kbps mp3 is re-encoded with libmp3lame defaults (~128 kbps CBR) -> silent quality/bitrate downgrade; same for aac/opus outputs
    - output extension mirrors the input, so `.wma` and `.aiff` inputs (in accepts) are re-encoded with ffmpeg's default/experimental wma encoder or pcm_s16be — poor or surprising results
    - target loudness is hardcoded -16 LUFS: unsuitable for Spotify (-14), broadcast (-23), or cinema; no override
    - fixed 0.3 progress, run_cmd blocking — no live progress on long files
    - a source that is already near -16 LUFS is still fully re-encoded (no no-op detection), incurring quality loss for no gain
- **Optimizations:**
    - switch to 2-pass loudnorm only when accuracy matters, or cache the first-pass JSON to avoid double full decode
    - pin output sample rate (`-ar 44100/48000`) after loudnorm to avoid the 192 kHz blow-up and reduce file size
    - set explicit codec+bitrate matched to the source so re-encode doesn't silently downgrade
- **Improvements:**
    - append `aresample`/`-ar` and preserve source sample rate to fix the loudnorm 192 kHz upsample surprise
    - carry the source bitrate/quality into the re-encode instead of encoder defaults
    - add a dynamic-vs-linear and target-LUFS choice; expose I/TP/LRA
- **Broader support:**
    - target-preset param (podcast -16, streaming -14, broadcast -23)
    - peak/RMS normalization modes in addition to EBU loudness
    - optional video passthrough so a video's audio can be normalized in place (currently audio-only accepts)
    - true-peak limiter control

#### Trim video  ·  `video-trim`  ·  _verified-working_

- **Edge cases:**
    - always re-encodes to mp4 (libx264 veryfast + aac) regardless of input: trimming a .webm/.mkv forces a full transcode -> slower and lossy even when a keyframe-aligned stream copy would suffice
    - `start` is a free string (only maxLength 12) passed straight to `-ss`: non-time garbage ('abc', '1:2:3:4') yields an opaque ffmpeg parse error surfaced as the generic 'check the start time' message; a leading-dash value like '-5' is consumed as the -ss value (no option injection thanks to shell=False) and clamped
    - input-side `-ss` accuracy depends on the container seek index; for formats without a reliable index (some .flv/.webm/raw) the cut can land slightly off the requested time
    - start beyond end-of-file -> empty output -> handled ('start time within the video'), good
    - duration up to 86400s (24h) combined with full re-encode on CPU is a guaranteed timeout for any real-length source
    - no `-map`: subtitles and secondary audio tracks are dropped from the clip
    - source with no audio: `-c:a aac` maps nothing and still succeeds video-only (fine), but there's no signal to the user that audio was absent
- **Optimizations:**
    - offer a lossless `-c copy` mode (keyframe-aligned) for instant, quality-preserving trims when frame-exact cuts aren't required
    - keep the input container/codec when possible instead of always transcoding to h264/mp4
    - `-ss` is already before `-i` (fast seek) — good; add `-avoid_negative_ts make_zero` to keep A/V in sync on copy trims
- **Improvements:**
    - pre-validate `start` (and derive/validate against probed duration) to reject nonsense before invoking ffmpeg and give a precise error
    - offer an end-time param in addition to duration (common user expectation)
    - surface a warning when start+duration exceeds the source length (output silently truncated)
- **Broader support:**
    - output-format choice (keep webm/mkv, or export gif/audio-only)
    - multiple-segment / cut-list trimming
    - frame-accurate vs fast-seek toggle
    - preserve subtitle/second-audio tracks via -map

#### Video thumbnail  ·  `video-thumbnail`  ·  _verified-working_

- **Edge cases:**
    - output is always a full-resolution JPEG: a 4K source yields a 4K jpeg with no scaling/size cap
    - HDR sources (BT.2020/PQ, e.g. iPhone/modern cameras) are captured without tonemapping -> washed-out or oversaturated thumbnails
    - `time` is a free string (maxLength 12) to `-ss`; garbage -> opaque ffmpeg error mapped to 'timestamp may be past the end' even when the real issue is a malformed timestamp
    - timestamp past EOF -> no frame -> handled, good
    - for containers lacking a seek index, input `-ss` may grab a frame slightly off the requested time
    - `-q:v 2` is fixed — no quality/size control; large frames at q2 can be sizeable
    - a fully black/blank frame at the default 00:00:01 (fade-ins, black leader) produces a useless thumbnail with no smart-frame selection
- **Optimizations:**
    - add an optional `scale=` to cap output dimensions so 4K frames don't produce oversized JPEGs
    - use `-frames:v 1 -update 1` explicitly and `-an -sn` to skip audio/subtitle demux
- **Improvements:**
    - add a `thumbnail` filter or scene-change detection to auto-pick a representative (non-black) frame
    - tonemap HDR inputs (zscale/tonemap) so captured frames look correct
    - validate the timestamp against probed duration and report 'timestamp X exceeds duration Y' precisely
- **Broader support:**
    - PNG/WebP output and a width/height param
    - contact-sheet / N-frames-at-interval mode
    - percentage-based position (e.g. 50% of duration) in addition to absolute time

#### Video to GIF  ·  `gif-from-video`  ·  _verified-working_

- **Edge cases:**
    - no pixel/frame budget: width up to 1920 * fps up to 30 * duration up to 60s (e.g. 1920x1080@30 for 60s) produces an enormous, near-uncompressed GIF — hundreds of MB to >1GB and heavy palettegen memory
    - GIF loops infinitely with no control (no loop-count / boomerang option)
    - `start` free string to `-ss` same as trim: garbage -> opaque failure mapped to 'check start time and duration'
    - start beyond end -> empty output -> handled
    - accepts `.gif` as input -> gif-to-gif resample works but is an odd/expensive round-trip
    - scale=width:-1 auto-height is fine for GIF (no even-dimension requirement), but very tall aspect ratios at width 1920 magnify the size problem
    - fixed palettegen stats_mode/diff and no dithering choice -> banding on gradients or shimmering on high-motion clips
- **Optimizations:**
    - add `paletteuse=dither=bayer:bayer_scale=` and `palettegen=stats_mode=diff` options to cut size/shimmer
    - cap total output pixels (width*fps*duration) and reject or auto-downscale before encoding to prevent giant GIFs
    - for high-motion, offer animated WebP/APNG which are dramatically smaller than GIF at similar quality
- **Improvements:**
    - enforce a soft size budget and surface an estimate before encoding
    - expose loop count and a boomerang/ping-pong option
    - validate start against probed duration for a precise error
- **Broader support:**
    - animated WebP / APNG / short mp4 outputs alongside GIF
    - end-time param and crop region
    - dither/palette-quality presets

#### Download from URL  ·  `media-download`  ·  _concern_

- **Edge cases:**
    - SSRF: the URL is any http(s) target with no host allowlist and no private-range block — yt-dlp's generic extractor will happily fetch http://localhost, 127.0.0.1, 169.254.169.254 (cloud metadata), or LAN hosts reachable from the WSL2 box
    - runs yt-dlp in-process (not via run_cmd) so job_timeout_seconds does NOT apply; only the RQ worker timeout bounds it — a live-stream URL never terminates and a 4K/long video downloads until disk fills
    - no `max_filesize`/size cap: max_upload_mb (512) only limits uploads, not downloads, so output can far exceed intended quotas and there is no disk guard
    - `noplaylist: True` silently downloads only the first entry of a playlist/channel URL — surprising when the user pastes a playlist link
    - yt-dlp extractors rot over time; a stale binary yields 'Unable to extract' failures on major sites with no auto-update path
    - no progress_hooks wired (quiet+noprogress set) despite ctx.progress being available -> UI sits at 0.2 for the entire download
    - audio mode hardcodes mp3 via FFmpegExtractAudio with no quality param; video mode forces merge to mp4 (fails/loses quality for codecs that don't fit mp4)
    - the final loop moves EVERY file left in workdir to output_dir; on a partially-failed run interrupted between download and move, stray .part/fragment files could be swept in (mitigated because exceptions raise before the move)
- **Optimizations:**
    - set `socket_timeout`, `retries`, and `max_filesize` in opts, and reject `is_live` entries up front to bound time and disk
    - wire yt-dlp progress_hooks to ctx.progress for real download progress
    - cap resolution (e.g. bestvideo[height<=1080]) by default to avoid pulling 4K/8K when unnecessary
- **Improvements:**
    - add an SSRF guard: resolve the host and reject private/loopback/link-local/metadata IP ranges before download
    - enforce a per-job output size ceiling and free-disk precheck
    - reject/flag live streams explicitly with a clear message
    - keep yt-dlp updated (ops) and pin a known-good version
- **Broader support:**
    - format/resolution and container selection params
    - subtitle download and yt-dlp --download-sections (time-range) support
    - optional playlist mode with a max-items cap
    - cookies/geo options for gated content (with explicit user opt-in)

#### Remove background noise  ·  `speech-denoise`  ·  _concern_

- **Edge cases:**
    - whole file is loaded into RAM: scipy wavfile.read of pcm_s16le plus the float32 copy plus noisereduce STFT buffers -> a 1-hour 48 kHz stereo clip is ~0.7 GB int16 + ~1.4 GB float32 + internal buffers -> multi-GB, OOM-prone on this CPU-only box with no duration/size guard
    - noisereduce/wavfile exceptions are NOT wrapped in ToolError: an empty/0-duration or sub-window-length audio makes nr.reduce_noise raise a raw exception that escapes as a non-user-safe generic job failure
    - decode forces pcm_s16le, so a 24-bit source is truncated to 16-bit before denoise (quality loss); the int32/uint8/float branches in the code are effectively dead because ffmpeg always emits s16le
    - video output path uses `-c:v copy` into an .mp4 container: an input .webm/.mkv carrying VP8/VP9 video copied into mp4 is non-standard/unplayable or fails outright
    - `-map 0:v:0` assumes a video stream exists: a video-extension file that is actually audio-only (audio-only .mov/.mp4) fails the map with an opaque error
    - only 0:a:0 is cleaned and remuxed — secondary audio tracks and all subtitles are dropped from the video output
    - stationary=True assumes steady broadband noise; on non-stationary noise (traffic, babble, keyboard) it under-cleans, and on clean speech it can attenuate the voice
    - runs in-process (noisereduce) with no run_cmd timeout — a long file can run for many minutes bounded only by the RQ worker
    - audio output re-encodes with ffmpeg default codec/bitrate for the extension (same silent-downgrade issue as normalize/extract)
- **Optimizations:**
    - consider ffmpeg's native `arnndn` (RNNoise) or `afftdn` filter instead of Python noisereduce: streaming, far faster, no full in-memory decode, and stronger on speech
    - decode to `pcm_f32le` to preserve dynamic range and skip the int->float conversion branches
    - process in chunks/windows rather than loading the entire signal, and parallelize the per-channel loop
    - for video, remux the cleaned audio back into the ORIGINAL container (copy video into its own container) instead of forcing mp4
- **Improvements:**
    - wrap the numpy/scipy/noisereduce section in try/except -> ToolError so empty/too-short/odd-format inputs fail with a user-safe message
    - guard against 0-duration and sub-STFT-window inputs before calling reduce_noise
    - choose the output container to match the input video codec (avoid VP9-in-mp4)
    - probe for a video stream before using `-map 0:v:0`; fall back to audio-only cleaning if none
- **Broader support:**
    - expose stationary/non-stationary mode and an optional user-provided noise sample
    - preserve/clean multiple audio tracks and keep subtitles
    - let the user pick output format/bitrate
    - noise-profile presets (fan, hum, hiss, HVAC)

#### Isolate vocals / instrumental  ·  `voice-isolation`  ·  _concern_

- **Edge cases:**
    - MDX-NET ONNX inference is CPU-only here (onnxruntime CPU): a typical 3-4 minute song can take minutes, and a long track can exceed the RQ worker timeout; runs fully in-process with no run_cmd timeout
    - first run downloads the model over the network to a default cache dir — on an offline/air-gapped self-host this fails with 'source separation failed', and there's no pre-bundled model or size/disk guard
    - model filenames are a fixed 2-item enum tied to UVR's external hosting; if those URLs move/rename, both options break with no fallback
    - concurrent voice-isolation jobs each load a separate model copy into RAM in their own worker process (no cross-job model cache) -> heavy memory + CPU contention on the CPU-only box
    - output MP3 is hardcoded (output_format='MP3') at the library default bitrate — no lossless (WAV/FLAC) option for a quality-sensitive separation task
    - output files are named by the library from the UUID input stem (e.g. '<uuid>_(Vocals)_<model>.mp3') -> opaque, non-human names
    - video inputs (.mp4/.mkv/.webm) rely on audio-separator's own ffmpeg demux; an input with no audio stream fails inside the engine as a generic error
    - available() imports audio_separator at every job-create (create_job calls tool.available()), adding import latency and coupling job creation to engine import health
- **Optimizations:**
    - cache/reuse the loaded Separator+model across jobs (or a warm long-lived worker) to avoid re-loading the ONNX model for every request
    - pin/pre-download the model files at deploy time so first-run isn't a network round-trip
    - limit heavy-queue concurrency for this tool specifically given per-job model memory footprint
    - expose ONNX thread count / segment size to tune CPU throughput
- **Improvements:**
    - surface real progress from the engine's callbacks instead of static 0.2/0.4/1.0 on a multi-minute op
    - pre-check network/model availability in available() with a clear 'model not downloaded' message
    - offer WAV/FLAC output for lossless stems
    - give outputs human-readable names (Vocals/Instrumental) rather than the UUID-derived library default
- **Broader support:**
    - Demucs-style 4-stem separation (vocals/drums/bass/other) in addition to 2-stem
    - output-format and bitrate selection
    - optional GPU path when hardware is present
    - batch/multi-file separation


### Subtitle tools

**Cross-cutting for this group:**

- Encoding is the dominant unhandled failure across all three tools: none pass a charset option (ffmpeg `-sub_charenc`, ffsubsync `--encoding`). Real-world subs are frequently CP1256/CP1251/GBK/Big5/Shift-JIS/Latin-1/UTF-16, so a large fraction of legitimate inputs will fail or garble. A shared 'detect charset, normalize to UTF-8' helper (charset-normalizer) would fix convert, extract-output, and sync at once.
- Success is judged only by `out.is_file() and st_size > 0`. That treats header-only/zero-cue outputs (e.g. 'WEBVTT\n\n', an empty SRT, a garbage-offset sync) as success. A shared 'output has >=1 real cue' validation (parse with pysubs2) would make all three report bad results honestly.
- Error messages collapse distinct causes into one string — most damagingly in subtitle-extract, where image-based (PGS/VobSub) tracks, out-of-range indices, and truly-absent subtitles all report 'no embedded subtitle track found'. An ffprobe-first step (list streams: index, codec, language, disposition) would let all tools validate up front and give accurate, actionable errors.
- Progress is hardcoded and coarse (0.3/0.4 then 1.0). None parse the underlying ffmpeg/ffsubsync progress, so long-running sync/extract jobs on CPU appear frozen. Parsing tool stderr for real progress would improve UX group-wide.
- Subtitle inputs get NO content/mime verification (the ARCHIVE_MIMES check in jobs.py is archive-only), so any binary renamed `.srt/.ass/.vtt` passes the accepts gate and only fails deep inside ffmpeg/ffsubsync with a raw stderr tail. A lightweight text-vs-binary sniff for subtitle categories would fail fast with a clean message.
- Format coverage is narrow (srt/vtt/ass/ssa only). Common formats — MicroDVD `.sub`, VobSub `.idx/.sub`, `.sbv`, TTML/`.dfxp`, SAMI `.smi`, LRC — are unsupported for convert/extract/sync despite being handled by ffmpeg/pysubs2/ffsubsync.

#### Convert subtitles (subtitle-convert)  ·  `subtitle-convert`  ·  _verified-working_

- **Edge cases:**
    - Non-UTF-8 input is the #1 real-world failure: run_cmd calls ffmpeg with NO -sub_charenc, so ffmpeg decodes the text subtitle as UTF-8. Legacy SRT/ASS in Windows-1256 (Arabic), CP1251 (Cyrillic), GBK/Big5 (Chinese), Shift-JIS, or Latin-1 either aborts ('Invalid UTF-8') or silently produces mojibake. These encodings are extremely common for downloaded subs. No detection is attempted.
    - UTF-16 / BOM inputs: a UTF-16 SRT (common from Windows tools) fails ffmpeg probing; a UTF-8 BOM can leak into the first cue index. Not handled.
    - Silent styling loss on lossy conversions: ASS/SSA -> SRT or -> VTT drops all styling (fonts, colors, \pos positioning, karaoke \k tags, layers, \p drawings), and VTT -> SRT drops cue settings/regions/STYLE blocks. ffmpeg does this without warning; user gets a technically-valid but stripped file and no notice.
    - Semantic-empty success: the only success check is `out.stat().st_size == 0`. A zero-cue source converted to VTT yields a header-only 'WEBVTT\n\n' (>0 bytes) which passes as success but is useless; likewise a nearly-empty SRT.
    - ssa/ass equivalence: `.ssa` is accepted and is the SAME format as ASS, but converting `.ssa` -> `ass` is allowed and is a near no-op (only the extension changes), while `.ass` -> `ass` is (correctly) blocked by the `src.suffix.lstrip('.') == to` guard. Inconsistent.
    - The 'already in that format' guard is extension-based only (`src.suffix.lower().lstrip('.') == to`). An ASS file mislabeled `.srt` (accepts gate matches on orig_name; subtitles get NO mime-content check unlike archives) would pass the guard and be handed to ffmpeg which content-probes it — result depends on ffmpeg's guess, not the extension.
    - ASS inline override tags (`{\i1}`, `{\an8}`, `{\c&H..&}`) convert unpredictably to SRT: some become <i></i>, positioning/color tags are dropped, drawing commands (`{\p1}`) produce empty/garbage cues.
    - WebVTT inline timestamp/karaoke tags (`<00:00:01.000>`) and voice spans (`<v Speaker>`) are stripped or mangled when going to SRT.
    - A binary/garbage file renamed `.srt` reaches ffmpeg (no content sniff for subtitle categories) and fails with the raw ffmpeg stderr tail rather than a clean 'not a subtitle file' message.
- **Optimizations:**
    - Add `-loglevel error` alongside `-hide_banner` to cut stderr parsing/log overhead (conversion is already single-pass so CPU is not the bottleneck).
    - Skip re-invoking ffmpeg when source and target are the same FORMAT family (ass/ssa) instead of only same extension — avoids a pointless remux.
    - Pre-detect charset once (charset-normalizer/chardet on the first ~64KB) and pass the resolved `-sub_charenc`, avoiding a failed full ffmpeg pass then a retry.
- **Improvements:**
    - Detect input encoding and pass `-sub_charenc <cp>` so non-UTF-8 subs convert to clean UTF-8 instead of failing/garbling; expose an optional `encoding` param override.
    - Warn (in job message) when a conversion is lossy (ASS/SSA -> SRT/VTT strips styling), so the user isn't surprised.
    - Validate the output is non-trivial (has at least one cue), not just non-zero bytes, so header-only/empty results are reported as failure.
    - Return a friendly 'this doesn't look like a subtitle file' error by pattern-matching ffmpeg's 'Invalid data'/'could not find codec' stderr instead of surfacing the raw tail.
- **Broader support:**
    - Add `.ssa` as a valid target (currently accepted as input but the `to` enum only offers srt/vtt/ass).
    - Support common formats seen in the wild: MicroDVD `.sub`, YouTube `.sbv`, TTML/`.dfxp`, SAMI `.smi/.sami`, LRC lyrics — all convertible via ffmpeg or pysubs2.
    - Optional 'strip styling' vs 'preserve styling' toggle, and an output-encoding param (e.g. force UTF-8 with/without BOM for Windows players).

#### Extract subtitles (subtitle-extract)  ·  `subtitle-extract`  ·  _verified-working_

- **Edge cases:**
    - Image-based subtitle tracks are the biggest real gap: MKV/MP4/TS routinely carry Blu-ray PGS (HDMV), DVD VobSub, or DVB bitmap subtitles. Forcing a `.srt` (text) output makes ffmpeg fail with 'Subtitle encoding currently only possible from text to text or bitmap to bitmap'. That error is caught and reported as 'no embedded subtitle track found ... may have no subtitles' — actively MISLEADING: the track exists but needs OCR, and the user is told it doesn't exist.
    - Track index is validated only by ffmpeg failing: any error from `-map 0:s:{track}` (out-of-range index, image codec, corrupt stream) collapses into the same generic 'no subtitle track found' message, so the user can't tell 'wrong index' from 'image-based' from 'truly none'.
    - `maximum: 30` on the track param is arbitrary; multi-language anime/film releases frequently have 30-40+ subtitle tracks, so higher tracks are unreachable.
    - No language selection: users think 'English', not stream index. There's no way to pick by `-map 0:s:m:language:eng`, and no way to see which index is which language/forced/SDH (disposition flags are ignored).
    - Forced-vs-full: a track that exists but is a 'forced' track with only a few signs, or a track with zero cues, can produce a tiny/empty output; the `size == 0` guard catches empty but a header-only/near-empty extraction reads as success.
    - AVI/`.ts` inputs: AVI almost never carries embedded text subs, and `.ts` PID-muxed DVB subs are typically bitmap — both usually hit the misleading 'no subtitles' path.
    - Styling loss: an embedded ASS track (common in MKV) forced to `.srt` loses all karaoke/positioning/styling; the tool can only ever emit SRT even when the source is richer.
    - Non-UTF-8 embedded text subs (rare but possible in old MP4 mov_text/legacy MKV) are re-encoded assuming source is decodable; no `-sub_charenc` control.
- **Optimizations:**
    - Run a quick `ffprobe -select_streams s -show_entries stream=index,codec_name:stream_tags=language` first to (a) validate the track index, (b) detect text vs bitmap codec, (c) list languages — failing fast and correctly instead of launching a full ffmpeg decode that ends in a misleading error.
    - Add `-loglevel error` and, since only the subtitle stream is mapped, ffmpeg already demuxes minimally — but ffprobe-gating avoids reading a large container at all when the request is invalid.
    - Choose the output muxer to MATCH the source codec (extract ASS as `.ass`, mov_text/webvtt as `.srt`/`.vtt`) to skip an unnecessary transcode and preserve fidelity.
- **Improvements:**
    - Distinguish the failure modes with real messages: 'track N is image-based (PGS/VobSub) — use OCR', 'only M subtitle tracks exist (0..M-1)', 'no subtitle streams found'. Currently all three are one string.
    - Detect image-based tracks up front and either reject with a clear message or (broader) route to an OCR path.
    - Surface the track list (index, language, codec, forced/default/SDH disposition) so the user can pick meaningfully rather than guessing an integer.
    - Validate the extracted file has >=1 cue, not just >0 bytes.
- **Broader support:**
    - Let the user choose output format (srt/vtt/ass) so an embedded ASS track can be extracted losslessly as `.ass`.
    - Support 'extract all tracks' producing one file per subtitle stream (named by language) in a single job.
    - Select track by language tag and/or by disposition (forced, default, hearing_impaired).
    - Raise/remove the arbitrary max-track cap (30) or derive the ceiling from ffprobe.

#### Sync subtitles (subtitle-sync)  ·  `subtitle-sync`  ·  _verified-working_

- **Edge cases:**
    - Subtitle-vs-subtitle sync is impossible even though ffsubsync natively supports it (align an unsynced sub against a known-good reference sub — fast, no audio). The classifier only sets `ref` from `_REF_EXT` (media), so two `.srt` inputs -> `ref` stays None -> ToolError. A common, cheap workflow is blocked.
    - Extra files silently ignored: multi_file with min_files=2 and NO upper bound. Upload video + two subtitles, or two videos + one sub, and the SECOND same-category file is dropped by the first-match-wins loop with no warning — the user may sync the wrong pair.
    - 600s hard cap (`min(job_timeout_seconds, 600)`) is too low for long films on CPU-only: ffsubsync must decode+VAD the entire reference audio; a 2.5-3h movie can exceed 10 min and get killed, surfacing as "'ffsubsync' timed out after 600 seconds" even though the sub is fine.
    - Wrong audio track: ffsubsync aligns to the DEFAULT audio stream. Files whose first/default track is director commentary or a dub align the subtitle to the wrong speech; no way to pick the audio track.
    - Framerate drift (PAL 25fps vs 23.976fps telecine) is THE classic sync case — needs framerate-ratio scaling, not just a constant offset. ffsubsync attempts common ratios by default but `--gss` (golden-section search) and `--no-fix-framerate` aren't exposed, so hard drift cases silently produce a still-drifting result.
    - Non-UTF-8 subtitle input: ffsubsync's `--encoding` isn't passed; a CP1256/CP1251/GBK sub may mis-decode or error.
    - VTT/ASS output fidelity: output keeps the source suffix (`{sub.stem}-synced{sub.suffix}`). ffsubsync round-trips VTT/ASS less robustly than SRT (historically SRT-first); styling/regions may be altered or the write may misformat.
    - Speech-poor references: music videos, silent films, heavy-score audio give VAD nothing to lock onto -> alignment fails. The 'audio may lack clear speech' fallback message is apt but there's no manual-offset escape hatch.
    - Bad-but-nonzero result: ffsubsync can 'succeed' with a garbage global offset (e.g. locks onto laughter/applause); output is non-empty so it passes the size check and is reported as done despite being worse than the input.
- **Optimizations:**
    - Fast path for sub-vs-sub (once supported): skip all audio decoding/VAD and align directly — orders of magnitude faster and doesn't need the heavy queue.
    - Pre-extract a mono 16kHz WAV via ffmpeg with `-threads`/`-ac 1 -ar 16000` and feed that to ffsubsync to avoid it re-decoding full-resolution audio.
    - Scale the timeout by reference duration (ffprobe the length) instead of a flat 600s, so long films aren't guillotined while short clips still fail fast.
    - Pass an explicit `--vad=webrtc` and cap `--max-offset-seconds` to bound the search and shorten runtime on clean inputs.
- **Improvements:**
    - Report and act on ambiguity: if >1 subtitle or >1 media file is provided, either error clearly or let the user designate which is the reference, instead of silently taking the first of each.
    - Emit real progress by parsing ffsubsync stderr (it prints phases) — currently jumps 0.3 -> 1.0, so a 10-minute job looks frozen.
    - Provide a manual-offset fallback (constant shift in seconds) for when auto-VAD fails, so the tool still delivers value on speech-poor audio.
    - Detect subtitle encoding and pass `--encoding`/`--output-encoding=utf-8` for reliable non-UTF-8 handling.
- **Broader support:**
    - Support subtitle reference (align sub against a reference subtitle), which ffsubsync already does — just needs the classifier to allow one sub as `sub` and another as `ref`.
    - Expose key ffsubsync knobs as params: audio-track index, `--gss`/framerate-fix toggle, `--max-offset-seconds`, VAD backend (webrtc/auditok/silero).
    - Accept `.sub`/`.sbv`/`.ttml` subtitle inputs (currently only srt/vtt/ass/ssa) for both the target and the reference.


### AI & RAG tools

**Cross-cutting for this group:**

- CONTEXT-WINDOW TRUNCATION IS THE HEADLINE BUG. _ollama.chat() posts {model, messages, stream:False} with NO options.num_ctx. Ollama therefore applies its default context (2048 tokens unless the model's Modelfile raises it), while _text_extract caps at 24000 chars (~6-8k tokens) and multi_doc_qa stuffs top_k=6 x 1500-char passages (~9k chars). Ollama silently left-truncates the prompt to fit num_ctx, dropping the SYSTEM message + the instruction + the START of the document/passages. Result: summaries/answers are silently computed from only the tail of the input, and doc_qa can wrongly say 'not in the document'. Every AI tool (ai_summarize, doc_qa, multi_doc_qa, audio_summary) is affected. Fix: pass options={'num_ctx': N} sized to the actual prompt (and consider truncating text to fit num_ctx explicitly).
- THINKING-TOKEN LEAKAGE: the configured chat model is qwen3:8b (config.py default), a reasoning model. _ollama.chat sends no 'think': false and returns message.content verbatim. Depending on Ollama version, <think>...</think> reasoning is emitted inside content, so summary/answer/notes output files can contain raw chain-of-thought. It also wastes large amounts of CPU-time per call. Pass think:false (or strip the thinking field). The running model per MEMORY is qwen2.5:3b which avoids this, but the committed default does not.
- NO STREAMING + 600s READ TIMEOUT: _ollama.chat is non-streaming (stream:False) with read=600s. An 8B model on CPU generating a 'detailed' summary of a long doc/transcript can exceed 600s, surfacing as 'could not reach the local AI service (Ollama)' with zero partial output and no progress between 0.5->1.0. Streaming would fix the timeout, enable real progress, and cut perceived latency.
- CONCURRENT SAME-MODEL LOAD: with 8 concurrent heavy jobs, transcribe/audio_summary each load their own faster-whisper model per worker PROCESS (small int8 ~0.5GB each), and all AI tools hammer a single Ollama instance simultaneously. No semaphore/queue-depth guard exists around the LLM; Ollama will queue or spin up parallel model copies (OLLAMA_NUM_PARALLEL) risking CPU oversubscription and OOM. Consider serializing heavy AI calls or limiting the heavy queue concurrency.
- IN-PROCESS OPERATIONS ARE NOT TIME-BOUNDED OR COOPERATIVELY CANCELLABLE: job_timeout_seconds only governs ctx.run_cmd subprocesses. model.transcribe() (a C loop in CTranslate2) and the blocking Ollama HTTP call run in-process with no per-op timeout; a multi-hour recording can run far past the intended 1800s budget, and a cancel request cannot interrupt the C decode loop or an in-flight chat mid-call.
- ACCEPT-LIST INCONSISTENCY across the audio path: transcribe accepts .wma/.aiff/.avi but audio_summary does NOT, so a .avi/.wma meeting recording can be transcribed but is rejected by the summarize-audio tool. Align the two accept lists.
- extract_text's 'truncated' return is discarded in multi_doc_qa (`text, _ = extract_text(... max_chars=200_000)`), so per-document 200k-char truncation is completely silent to the user (separate from the 200-chunk note).

#### Transcribe audio / video (faster-whisper)  ·  `transcribe`  ·  _verified-working_

- **Edge cases:**
    - 0-duration / silent / music-only / no-speech input: info.duration=0 -> total=0 -> progress never advances past 0.10, segs is empty, and it writes an EMPTY .txt/.srt (or bare 'WEBVTT\n') with NO error. audio_summary raises 'no speech detected' in the same situation; transcribe should too.
    - Video with no audio stream: faster-whisper/PyAV decode_audio raises a bare exception (not ToolError) -> generic job failure instead of a clean 'no audio track' message.
    - Invalid/unsupported language code (param is a free string, maxLength 10, not validated): faster-whisper raises ValueError('language X is not supported') uncaught -> ugly failure rather than a ToolError listing valid codes.
    - Very long media (2-3h podcast): transcription runs in-process with NO timeout guard; can run for tens of minutes on CPU int8 small, blowing the 30-min job budget.
    - Whisper hallucination on non-speech/long silence: repeated phantom text; no no_speech_threshold / condition_on_previous_text=False tuning, VAD alone doesn't fully prevent it.
    - Segment with start set but end=None -> `s.end or 0` yields a 00:00:00 end timestamp in srt/vtt.
    - Output filename is `{src.stem}.{ext}` where stem is the uuid-named input, so the user downloads e.g. 3f2a...c1.srt losing the original filename (UX).
    - Code-switching / multilingual audio: single detected language applied to the whole file; other-language segments transcribed poorly.
    - num_ctx not relevant here, but json output only carries segment-level timing (no word timestamps) even though callers may want them.
- **Optimizations:**
    - Set WhisperModel(cpu_threads=...) and num_workers explicitly: default cpu_threads=0 lets CTranslate2 grab all cores, so multiple concurrent heavy workers oversubscribe the CPU and slow each other down.
    - Expose/lower beam_size (default 5) — beam_size 1-2 is markedly faster on CPU with modest accuracy loss.
    - Use faster_whisper.BatchedInferencePipeline for a large throughput gain on long files.
    - For txt output, stream segment text to disk instead of materializing the full `segs` list (only srt/vtt/json truly need the list).
    - Model is already shared via module-global _MODEL and reused by audio_summary — good; keep that.
- **Improvements:**
    - Raise a clean ToolError('no speech detected') on empty segments instead of writing an empty file.
    - Validate `language` against faster_whisper.tokenizer._LANGUAGE_CODES and return a helpful error.
    - Wrap decode in try/except -> ToolError('could not decode audio / no audio track').
    - Emit the detected language + duration (e.g. a header line in txt, or always alongside output) so users know what was detected.
    - Add a per-job wall-clock timeout around the transcribe loop so runaway long files fail predictably.
- **Broader support:**
    - Expose task='translate' (Whisper can translate any language to English) — currently unreachable.
    - Add word_timestamps and initial_prompt (domain vocabulary/spelling) params.
    - Additional output formats: tsv, csv, plain paragraphs.
    - Accept more containers: .ts, .3gp, .amr, .wmv (has .wma audio but not .wmv video), .flv.
    - Speaker diarization (documented GPU/HF-token roadmap item).

#### AI Summarize (Ollama LLM)  ·  `ai-summarize`  ·  _concern_

- **Edge cases:**
    - Long documents are HARD-TRUNCATED to the first 24000 chars (~15 pages) then summarized; a 300-page PDF yields a summary of only its opening. No map-reduce. The note tells the user it was truncated but the summary silently ignores the bulk of the content.
    - Compounded by the num_ctx cross-cutting bug: even the 24000 chars overflow Ollama's default context, so the system prompt + length instruction + start of the doc get left-truncated away, degrading or nullifying the short/medium/detailed instruction.
    - DOCX with content in TABLES, headers/footers, text boxes, or footnotes: _from_docx reads only document.paragraphs, so a table-heavy .docx extracts little/no text -> 'no text could be extracted' or a summary missing the real content.
    - Non-UTF8 .txt (Windows-1252, UTF-16/BOM): read with errors='replace' -> mojibake / replacement chars fed to the model; UTF-16 is badly mangled.
    - Encrypted PDF: surfaces the generic 'could not read the PDF (it may be encrypted or corrupt)' rather than the clear password message pdf_merge gives.
    - Arabic/RTL output selectable, but qwen2.5:3b/qwen3:8b produce weak Arabic — quality, not a crash.
    - Scanned/image-only PDF correctly raises the 'run OCR first' ToolError (good).
- **Optimizations:**
    - Set options.num_ctx to fit the prompt and set keep_alive to keep the model resident between jobs (avoids per-job reload on CPU).
    - Map-reduce: chunk-summarize then combine, instead of discarding everything past 24000 chars.
    - Stream the response to update progress and dodge the 600s read-timeout cliff on long generations.
- **Improvements:**
    - Chunked/hierarchical summarization for long docs.
    - Extract docx tables/headers/footers and detect text encoding (charset-normalizer) in the shared extractor.
    - When truncation happens, tell the model (and user) which portion was summarized.
    - Guard against an empty model response (chat() can return '' for a thinking-only reply) before writing the file.
- **Broader support:**
    - Accept .rtf, .odt, .html, .epub, .pptx, .csv.
    - Allow summarizing pasted text or a URL (no file).
    - Target-length-by-word-count and output-format (bullets vs prose vs abstract) params.

#### Ask a document / doc-qa (single-doc LLM QA)  ·  `doc-qa`  ·  _concern_

- **Edge cases:**
    - Answer-not-found false negatives: if the answer lies past the 24000-char cap OR past Ollama's default num_ctx, the model is told to answer ONLY from the provided document and will correctly-but-wrongly reply 'not in the document' because that part was truncated away. This is the most user-visible symptom of the num_ctx bug.
    - Documents larger than the context window are silently truncated rather than being routed to the RAG tool (multi-doc-qa); the user gets a confidently wrong 'not found'.
    - Prompt injection: document text containing 'ignore previous instructions...' can hijack the answer; grounding is by instruction only, no isolation. Low risk for single-user local, but real.
    - Same DOCX-tables/headers and non-UTF8 extraction gaps as ai-summarize (shared _text_extract).
    - Question in a different language than the document — answer quality depends entirely on the small model.
- **Optimizations:**
    - options.num_ctx sizing + keep_alive + streaming (same as ai-summarize).
    - Short-circuit: if extracted text comfortably fits, skip the truncation note logic; if it doesn't, warn instead of silently trimming.
- **Improvements:**
    - Return a supporting excerpt/quote from the document alongside the answer for verifiability.
    - When the doc exceeds the context budget, auto-suggest or auto-delegate to multi-doc-qa (RAG) instead of truncating.
    - Guard empty model output; strip any leaked <think> block before writing answer.txt.
- **Broader support:**
    - Batch/multiple questions in one job.
    - Return a confidence or 'answer found: yes/no' flag.
    - Accept the same extra formats as summarize (rtf/odt/html/epub/pptx).

#### Chat with documents / multi-doc-qa (RAG)  ·  `multi-doc-qa`  ·  _concern_

- **Edge cases:**
    - 200-chunk global cap has an ORDERING BIAS: passages are appended in upload order then sliced passages[:200]. With many/large docs the cap is filled by the FIRST documents and LATER DOCUMENTS ARE DROPPED ENTIRELY, so a question answerable only from doc #8 silently fails. The 'only the first passages were indexed' note undersells that whole files were skipped.
    - Retrieved context still overflows Ollama's default num_ctx: top_k=6 x 1500 chars (~9k chars) + question is left-truncated by the chat call (cross-cutting bug), so even correctly-retrieved passages get partially dropped before the model sees them.
    - nomic-embed-text is used WITHOUT its recommended task prefixes ('search_document:' for chunks, 'search_query:' for the question). Retrieval recall/precision is measurably worse than intended.
    - Per-document 200k-char truncation is silent (extract_text truncated flag discarded).
    - A single embed failure (any chunk) raises ToolError and aborts the whole job after possibly embedding 199 chunks — no skip/retry; wasted work.
    - No chunk deduplication: near-duplicate passages across docs can fill the top_k, wasting the (already tight) context budget on repeats.
    - Empty/whitespace docs: _chunk strips+skips empties, and all-empty input raises the clean 'no text could be extracted' ToolError (good).
    - Same DOCX-tables/headers and non-UTF8 extraction gaps via _text_extract.
- **Optimizations:**
    - BATCH EMBEDDINGS: replace up to 200 sequential POSTs to the deprecated /api/embeddings (singular) with array input to /api/embed — one (or few) request(s) instead of 200. Biggest single speedup here.
    - Deduplicate identical/near-identical chunks before embedding.
    - Set options.num_ctx on the final chat so retrieved context actually fits.
    - The whole index is rebuilt from scratch on every question (ephemeral by design) — offer an optional persisted index for repeated Q&A over the same docs.
- **Improvements:**
    - Round-robin / proportional chunk selection across documents so the 200-cap doesn't starve later files; report which documents were actually indexed.
    - Add nomic task prefixes to both chunks and query.
    - Skip-and-continue on individual embed failures instead of aborting.
    - Return similarity scores and passage offsets with the cited [source] names for verifiability.
    - Guard empty LLM output; strip leaked <think>.
- **Broader support:**
    - Hybrid retrieval (BM25 + vector) and a rerank step for better grounding on the small model.
    - Persist/reuse the embedding index across jobs for the same document set.
    - Accept the same extra document formats as the other AI tools.
    - Expose chunk size/overlap and embedding model as params.

#### Summarize audio (notes) / audio-summary  ·  `audio-summary`  ·  _concern_

- **Edge cases:**
    - Long meetings are SILENTLY truncated: transcript[:24000] feeds only ~the first 25 minutes to the LLM, and unlike ai_summarize there is NO truncation note — action items/decisions from the back half of a 2-hour recording just vanish with no warning.
    - num_ctx cross-cutting bug compounds this: 24000 chars overflow the default context so the notes instruction + transcript start are left-truncated.
    - No language / task param (always auto-detect) — inconsistent with the transcribe tool and no way to force a language or translate.
    - Whisper hallucination on music/applause/silence -> hallucinated transcript -> plausible-looking but fabricated 'meeting notes'.
    - Accept list omits .wma/.aiff/.avi that transcribe supports, so those recordings are transcribable but not summarizable.
    - No-speech input correctly raises 'no speech was detected' (good, better than transcribe).
    - Long in-process transcription can exceed the job time budget (no per-op timeout).
- **Optimizations:**
    - Reuse/share the faster-whisper model via transcribe._get_model (already done — good).
    - Map-reduce the transcript for long recordings instead of truncating at 24000.
    - Same LLM wins: options.num_ctx, keep_alive, streaming, think:false.
    - Optionally accept a pre-existing transcript to skip STT entirely.
- **Improvements:**
    - Add a truncation note when transcript > 24000 chars (parity with ai_summarize).
    - Add language/translate params.
    - Timestamped action items / decisions by feeding segment timings, not just joined text.
    - Guard empty LLM notes output.
- **Broader support:**
    - Accept a pre-made transcript (.txt/.srt/.vtt) as input to summarize without re-transcribing.
    - Structured output (markdown / json with summary + decisions + action-items).
    - Align accept list with transcribe (.avi/.wma/.aiff) and add diarization (GPU roadmap).

#### _ollama shared client  ·  `_ollama`  ·  _concern_

- **Edge cases:**
    - No options.num_ctx on chat() -> silent left-truncation of every long prompt (headline cross-cutting bug).
    - No think:false -> qwen3 reasoning tokens may leak into returned content and burn CPU-time.
    - chat() returns content.strip() with no empty-string guard: a thinking-only or empty reply becomes '' and callers write an empty output file with no error.
    - embed() uses the deprecated singular /api/embeddings (no batch capability) — forces the 200x sequential loop in multi-doc-qa.
    - available() only pings /api/tags; it does NOT verify settings.ollama_model is actually pulled, so ai_summarize/doc_qa/audio_summary advertise as available and only fail at run time with the 404 ToolError.
    - has_model uses startswith(prefix): 'nomic-embed-text' matches 'nomic-embed-text:latest' (fine) but would also match an unintended 'nomic-embed-text-v2' — loose prefix matching.
    - 600s chat read timeout can be hit by an 8B model on CPU -> surfaces as 'could not reach the local AI service' even though the service is fine (misleading message).
    - No retry on transient httpx.HTTPError; a single blip fails the job.
- **Optimizations:**
    - Add options={'num_ctx': N, 'keep_alive': ...} and reuse a single module-level httpx.Client instead of creating a new client per get/post.
    - Switch embed to the batch /api/embed endpoint and accept a list of texts.
    - Add think:false to skip reasoning generation on qwen3.
    - Add a small bounded retry/backoff for connect errors.
- **Improvements:**
    - Pre-check the chat model in available() (has_model(settings.ollama_model)) so unavailability is reported before a job is accepted.
    - Enforce/normalize prefix matching in has_model (exact base-name match).
    - Guard and raise ToolError on empty chat content.
    - Add an optional concurrency semaphore so N heavy workers don't stampede a single CPU Ollama instance.
- **Broader support:**
    - Expose num_ctx / temperature / top_p / max tokens as tunables from settings.
    - Support streaming responses to callers (progress + timeout resilience).
    - Support alternate embedding endpoints/models and a batch embed API.

#### _text_extract shared extractor  ·  `_text_extract`  ·  _concern_

- **Edge cases:**
    - Big PDFs (e.g. 10k pages): _from_pdf extracts text from ALL pages into one string and truncates AFTERWARD, so a huge PDF is fully parsed (slow, high memory) even though only 24000 (or 200000) chars are used — can itself blow the job time budget.
    - DOCX tables, headers/footers, footnotes, text boxes are ignored (only document.paragraphs) — table-centric .docx extract to near-empty.
    - Non-UTF8 .txt: read_text(encoding='utf-8', errors='replace') mangles Windows-1252/Latin-1 and especially UTF-16/BOM files into replacement chars; no encoding detection, no BOM strip.
    - pypdf.extract_text() is weak on multi-column layouts, ligatures and spacing -> word-run-together / garbled text degrading all downstream summarize/QA quality.
    - Encrypted PDF often returns empty page text without raising -> surfaces as generic 'no text could be extracted (may be scanned)' instead of a clear password message (inconsistent with pdf_merge's nice password error).
    - max_chars cut is a raw character slice; fine for a decoded str but can split mid-sentence/mid-markdown-token.
- **Optimizations:**
    - Early-exit the PDF page loop once accumulated length >= max_chars (avoids parsing thousands of unused pages).
    - Swap pypdf for PyMuPDF (fitz) or pdfminer for much faster and higher-fidelity extraction.
    - Accumulate with a running length check rather than building the entire text then slicing.
- **Improvements:**
    - Extract docx tables, headers/footers, and footnotes.
    - Detect encoding (charset-normalizer) and handle UTF-16/BOM for .txt.
    - Distinguish password-protected from corrupt PDFs (mirror pdf_merge's PasswordError handling) for a clearer message.
    - Emit page markers so doc-qa/RAG can cite page numbers.
- **Broader support:**
    - .rtf, .odt, .html, .epub, .pptx, .csv extractors.
    - Optional OCR fallback (tesseract) for scanned/image-only PDFs instead of just telling the user to OCR first.
    - Return page/section structure metadata, not just flat text.


### Utility tools

**Cross-cutting for this group:**

- Any non-ToolError exception is swallowed by worker.py:174-179 into a generic 'internal error while running the tool' with no detail. Several concrete failures in this group hit that path instead of a clean message: gzip EOFError on truncated .gz, RuntimeError('File is encrypted') on password zip, Pillow ImportError in barcode PNG save, and hashlib.new('md5') ValueError under OpenSSL FIPS. Wrapping engine calls to translate known failures into ToolError would make these actionable.
- Friendly-name restoration is fragile: inputs are stored as <uuid><suffix> and _rename_outputs (worker.py:65-87) only renames top-level output files whose name startswith the uuid stem. Tools that put names elsewhere do not benefit: archive-compress writes uuid names as zip arcnames, archive-extract writes uuid-derived inner filenames, and gz output drops the extension entirely (<uuid>). Result: uuid-named or extension-less downloads.
- storage.safe_suffix keeps only the final Path.suffix, so multi-part extensions are destroyed at upload: 'backup.tar.gz' is stored as <uuid>.gz. archive-extract then dispatches on that stored suffix, so .tar.gz is only gunzipped, never un-tarred. Any tool whose behavior depends on a compound extension is affected by this upstream truncation.
- Description-vs-behavior mismatches across the group: metadata-remove claims to strip PDF/Office 'document metadata' but exiftool only marks PDF metadata deleted (recoverable) and barely touches OOXML; hash-checksum says 'verify its integrity' but only computes (no compare); archive-extract advertises .tar.gz support it does not fully deliver. These over-promise relative to the engine.
- available() gating is inconsistent: barcode-generate checks only 'import barcode' not Pillow (needed for PNG), virus-scan ignores settings.clamav_enabled and probes the socket directly, and metadata/archive tools defer the external-binary check to runtime (exiftool missing surfaces only as a run_cmd FileNotFoundError). Engine/definition versions (exiftool, ClamAV signature date, zlib) are never recorded in outputs, so results have no provenance.

#### Remove metadata  ·  `metadata-remove`  ·  _concern_

- **Edge cases:**
    - PDF: exiftool '-all=' does NOT truly remove metadata — it appends an incremental-update revision that marks the Info dict/XMP as deleted while the original bytes remain in the file and are trivially recoverable (exiftool itself warns of this). 'Remove metadata' gives false assurance for the very format users most want scrubbed.
    - Office (docx/xlsx/pptx are ZIP/OOXML): exiftool writing to OOXML is very limited — it does not strip docProps/core.xml (author, lastModifiedBy), docProps/custom.xml, comments, tracked changes, or embedded thumbnails. The advertised 'document metadata' removal is largely a no-op for Office files.
    - JPEG EXIF Orientation: '-all=' deletes the Orientation tag without first baking rotation into pixels, so phone photos that relied on Orientation now display sideways/upside-down after 'cleaning'.
    - HEIC/HEIF: many exiftool builds are read-only for HEIC writing; '-overwrite_original' then exits nonzero and surfaces as a generic "exiftool failed" ToolError, even though .heic/.heif are advertised in accepts.
    - shutil.copy2 (line 28) preserves the source filesystem mtime on the cleaned copy, leaking the original modification time even after in-file metadata is stripped.
    - No post-verification: exiftool reporting '0 image files updated / 1 unchanged' (nothing to strip, or a format it can't write) still exits 0 and the job silently reports success.
- **Optimizations:**
    - exiftool spins up a Perl interpreter per invocation (~100-200ms fixed cost); for repeated use a -stay_open/-execute pipe would amortize startup.
    - Avoid the shutil.copy2 of up to 512MB followed by in-place overwrite: use 'exiftool -o <output_dir>/name' to write the stripped file directly in one pass instead of copy-then-rewrite.
- **Improvements:**
    - For PDF, follow exiftool with a qpdf/pikepdf full rewrite (linearize) so the deleted metadata is not recoverable from prior revisions.
    - Preserve display orientation: auto-rotate pixels or keep the Orientation tag ('-Orientation') instead of blanket '-all='.
    - Emit a result file listing tags removed (tag count before/after) and surface exiftool 'unchanged'/warning output instead of hiding it.
    - Detect the read-only-format case and return a specific message ('this HEIC build cannot be rewritten') rather than a generic exit-code error.
- **Broader support:**
    - Video/audio metadata (mp4/mov/mkv/mp3/flac) via ffmpeg -map_metadata -1 -map_chapters -1.
    - A 'keep-list' mode to preserve chosen tags (ICC color profile, orientation) while stripping the rest.
    - A GPS-only strip mode for location scrubbing without destroying other EXIF.

#### Compress files  ·  `archive-compress`  ·  _concern_

- **Edge cases:**
    - Zip/7z entries are added with arcname=path.name where path.name is the internal '<uuid>.<ext>' (lines 39, 49), so the archive contains uuid-named files (e.g. 9f3c1a2b-....pdf), not the user's original names. _rename_outputs only renames the outer archive.zip, never the entries — original filenames are permanently lost inside the archive.
    - Because inputs are per-uuid, two files both named 'report.pdf' end up as two distinct uuids with no collision, but the user cannot tell them apart in the extracted result.
    - No password/encryption option despite bundling potentially sensitive documents into a single downloadable file.
    - Zip entries record the file's filesystem mtime (= upload time), so every timestamp in the archive is 'now' rather than the original file time.
    - 7z branch: if py7zr write fails partway, a partial archive.7z is left in output_dir; the job fails so it isn't registered, but the stray file lingers until retention cleanup.
- **Optimizations:**
    - Already-compressed inputs (jpg/png/mp4/zip/7z/pdf) are re-DEFLATED at full CPU cost for near-zero size gain; detect by extension/mime and use ZIP_STORED for them.
    - 7z default LZMA2 is slow on this CPU-only box; expose or cap the preset (e.g. default to a faster filter for large inputs).
    - No compresslevel is exposed (zipfile defaults to level 6); allow level 0-9 so users can trade speed vs size.
- **Improvements:**
    - Map arcname back to the sanitized orig_name from the File rows so the archive is human-readable, de-duplicating collisions with a numeric suffix.
    - Set the UTF-8 flag on zip entries (ZipInfo) once real, possibly non-ASCII names are used.
    - Write to a temp path and atomically rename into output_dir so a mid-write failure never leaves a partial archive.
- **Broader support:**
    - tar.gz / tar.xz output formats and a compression-level param.
    - Optional AES-encrypted zip (pyzipper) or 7z password.
    - Split/volume archives for large bundles; preserve directory structure if folder uploads are ever supported.

#### Extract archive  ·  `archive-extract`  ·  _concern_

- **Edge cases:**
    - .tar.gz is NOT fully extracted: storage stores it as '<uuid>.gz' (safe_suffix keeps only the final suffix), so dispatch (src.name.lower().endswith) hits _extract_gz and only gunzips to a single '<uuid>' .tar file instead of un-tarring it. The tar branch's '.tar.gz'/'.tar.bz2'/'.tar.xz' cases are effectively dead for uploaded files; only '.tgz' preserves its suffix and works.
    - Truncated/incomplete gzip raises EOFError (not OSError) from gzip.read, so the 'except OSError' at line 146 misses it and the job dies with the generic 'internal error' instead of 'not a valid gzip archive'.
    - Password/encrypted zip: zf.open(info) at line 83 raises RuntimeError('File is encrypted'), which is uncaught → generic internal error with no hint that a password is required.
    - 7z zip-bomb gap: the size guard relies on header-declared getattr(i, 'uncompressed', 0) and there is NO compression-ratio check for 7z at all (unlike zip). A crafted/streamed 7z with missing/zero declared sizes passes the 2 GiB guard, then zf.extractall() expands everything at once.
    - 7z symlinks are not rejected — only the tar branch checks issym()/islnk(). py7zr restores symlinks, so a 7z symlink entry can point outside the extraction dir or at sensitive paths after extraction.
    - gz output loses its extension ('<uuid>.gz' -> '<uuid>'), so the decompressed file has no suffix and downstream mime/labeling is generic.
    - A large archive registers every extracted file as its own DB File row (up to MAX_ENTRIES=10k) and _register_outputs + _rename_outputs rglob the whole tree — heavy for many small files.
- **Optimizations:**
    - Zip progress is only reported every 50 entries (idx % 50); an archive of a few very large members shows no progress movement during the long copies.
    - 7z uses zf.extractall which can buffer heavily on CPU-only; per-member extraction with running size accounting would bound memory and enable a real ratio check.
    - gz uses a 64KB read loop which is fine; the total-bytes guard is streamed correctly (good).
- **Improvements:**
    - Dispatch on sniffed magic/mime rather than the truncated stored suffix, or peek/try tarfile.open so .tar.gz is fully extracted.
    - Catch EOFError (truncated gz), RuntimeError (encrypted zip), and py7zr password errors and convert them to friendly ToolError messages.
    - Add a 7z compression-ratio check and 7z symlink rejection to match the zip/tar guards.
    - Bundle extracted results into a single folder/archive or cap registered outputs to avoid creating up to 10k File rows per job.
- **Broader support:**
    - Read support for .bz2, .xz, .zst, .lz4 standalone and .rar (read-only).
    - Password param for encrypted zip/7z.
    - Multi-part / split archive reassembly.

#### QR code  ·  `qr-generate`  ·  _verified-working_

- **Edge cases:**
    - Error correction is hard-coded to 'm' (line 53); no L/Q/H control, so users who want a logo overlay or higher damage tolerance can't get it.
    - Non-ASCII text is encoded as UTF-8 bytes with no ECI designator; many scanners assume ISO-8859-1 and render accented/CJK content as mojibake.
    - maxLength=2000 chars but QR byte capacity at ECC-M is ~2331 bytes; 2000 multibyte characters can exceed capacity and segno raises DataOverflowError (caught -> 'too long'). The character limit doesn't reflect the real byte limit, so failure is input-dependent and surprising.
    - scale up to 50 on a version-40 symbol (177 modules) yields an ~8850px PNG; there's no output-pixel cap, so worst-case memory/disk is large.
    - No quiet-zone/border control and scale=1 produces a technically-valid but usually unscannable image.
- **Optimizations:**
    - Generation is already fast and SVG output avoids rasterization; little to gain. Could skip re-encoding by reusing the segno object if multiple formats were ever requested.
- **Improvements:**
    - Expose error level, border/quiet-zone, module color and background as params.
    - Auto-select the minimal error level that still fits when data is large, and report the chosen version/ECC in a sidecar.
    - Add an ECI/encoding hint for non-Latin text to avoid scanner mojibake.
- **Broader support:**
    - PDF/EPS output and data-URI output.
    - Structured-append (multi-symbol) for data beyond single-symbol capacity.
    - Helper modes for wifi/vCard/geo/mailto payloads.

#### Barcode  ·  `barcode-generate`  ·  _concern_

- **Edge cases:**
    - available() checks only 'import barcode' (line 32) but PNG rendering needs Pillow; if Pillow (or its bundled font) is missing, the failure happens inside obj.save() (line 56) which is OUTSIDE the try/except, so it becomes an uncaught exception -> generic 'internal error'. SVG output would still work, making the failure format-dependent and confusing.
    - python-barcode ImageWriter renders human-readable text with a bundled TrueType font; on a stripped system without that font file, save() raises — again outside the try/except.
    - Code39 is uppercase-only; lowercase input is invalid and produces the same single generic 'not valid for a code39 barcode' message with no hint to uppercase.
    - Code39 (and some symbologies) default to add_checksum=True, silently altering the encoded value relative to what the user typed.
    - EAN/UPC/ISSN wrong digit count, bad checksum, or non-digit characters all collapse to one generic error string, so users can't tell which rule they violated.
    - 'if not saved' (line 57) never triggers in practice because .save() returns the output path; a genuinely empty render wouldn't be detected.
- **Optimizations:**
    - Rendering is cheap; negligible headroom. No re-decoding or caching concerns here.
- **Improvements:**
    - Extend available() to verify PIL specifically for the png path, and wrap obj.save() in try/except -> ToolError.
    - Expose write_text, module width/height, font size, DPI, quiet zone, and foreground/background color as params.
    - Surface the specific validation failure per symbology (required digit count, allowed charset) instead of one generic message.
- **Broader support:**
    - Add DataMatrix, PDF417, ITF/ITF-14, Codabar, GS1-128, and PZN symbologies.
    - Batch generation of multiple codes in one job.
    - PDF output alongside PNG/SVG.

#### File checksum  ·  `hash-checksum`  ·  _verified-working_

- **Edge cases:**
    - hashlib.new('md5') raises ValueError under OpenSSL FIPS mode (md5 disabled); with the default algorithm='all' this kills the whole job with a generic 'internal error'.
    - Output format is 'algo: hexdigest', which is NOT compatible with 'md5sum -c'/'sha256sum -c' (they expect '<hash>  <filename>'), despite the tool's stated integrity-verification purpose.
    - Only the first input is hashed (multi_file=False); a user selecting several files silently gets hashes for just one.
    - The description says 'verify its integrity' but the tool only computes hashes — there is no compare-against-expected path.
- **Optimizations:**
    - 'all' already hashes in a single pass with 4 hashers over one read (lines 39-42) — good. For the single-algo case, hashlib.file_digest (3.11+) is faster.
    - The 1 MiB read buffer is reasonable but a 4-8 MiB buffer cuts Python-loop overhead on 512 MB files; hashlib releases the GIL for large updates, so bigger chunks improve throughput.
- **Improvements:**
    - Add an optional 'expected' param and report MATCH/MISMATCH so the tool actually verifies.
    - Emit coreutils-compatible lines ('<hash>  <origname>') so output is directly usable with sha256sum -c.
    - Include the original filename and size in checksums.txt for provenance.
- **Broader support:**
    - Add crc32, sha224, sha384, sha3-256, and blake2b algorithms.
    - Support hashing multiple files / emitting a SHASUMS-style manifest.

#### Virus scan  ·  `virus-scan`  ·  _concern_

- **Edge cases:**
    - clamd StreamMaxLength (default 25 MB, often 100 MB) is far below max_upload_mb=512. A file over the limit makes clamd abort and close the socket mid-send, so s.sendall raises BrokenPipeError (OSError) -> mapped to 'could not reach the virus scanner' (line 56), which is misleading — the daemon is fine, the file is just too big to stream.
    - The 60 s socket timeout (line 13) is hard-coded and independent of job_timeout_seconds; a large/slow scan raises TimeoutError (OSError) -> same generic 'could not reach' message.
    - Error replies like 'INSTREAM size limit exceeded' or '... ERROR' don't end with 'OK' and don't contain 'FOUND', so they fall through to verdict = reply (line 65) and the job is marked DONE with an error string presented as a scan result — a scan failure reported as success.
    - available() ignores settings.clamav_enabled and probes the socket directly (lines 44-48), so behavior can diverge from the configured flag (enabled=False but a daemon listening still runs).
    - Under concurrency, clamd MaxThreads/MaxConnectionQueueLength can refuse connections -> OSError -> generic error, with no retry/backoff.
    - Virus-definition freshness is invisible; a stale signature DB yields a false 'CLEAN — no threats found' with no warning.
- **Optimizations:**
    - 64KB chunking is fine; could probe clamd VERSION/STATS once and cache it, and use zINSTREAM via a persistent IDSESSION if multiple files were ever scanned in one job (currently single file).
    - Use clamd PING/PONG in available() instead of a bare TCP connect to confirm the daemon is actually responsive, not just accepting connections.
- **Improvements:**
    - Distinguish size-limit / timeout / connection errors from clean/infected and raise a specific ToolError (e.g. 'file exceeds the scanner's stream size limit').
    - Treat any reply containing 'ERROR' as a scan failure (ToolError), not a written result.
    - Pre-check file size against clamd StreamMaxLength (or fall back to CONTSCAN of a temp path) so large files fail early with a clear message.
    - Record ClamAV engine + signature DB version in scan-result.txt for auditability.
- **Broader support:**
    - Per-entry results for archive contents (clamd already recurses into archives).
    - Scan multiple files in one job with a combined report.
    - Report-only vs quarantine option, and expose the matched signature category.


### Infrastructure · API · security · worker

**Cross-cutting for this group:**

- No reconciliation/reaper anywhere: a job can be committed status='queued' with rq_job_id=None in create_job (jobs.py:150-158 commits BEFORE enqueue) — if the API crashes between the two commits, or Redis is down when enqueue runs but recovers, the job sits queued forever. Likewise a worker killed mid-run (OOM/SIGKILL/RQ death penalty) leaves status='running' forever. cleanup.py explicitly SKIPS queued/running rows (ACTIVE_STATUSES), so their uploads AND tmp dirs are never purged. Add an age-based reaper (running > job_timeout*2 -> error; queued with dead/absent RQ job -> error) using RQ StartedJobRegistry/FailedJobRegistry.
- RQ forks a fresh work-horse per job (default Worker in worker.py:195), so ANY in-process cache is discarded every job: faster_whisper._MODEL (transcribe.py:11) is reloaded from disk for every single transcription despite the docstring claiming 'loaded once per worker process' — the lazy load happens inside the forked horse, not the parent. Preload heavy models in the parent before Worker.work(), or run cheap-tool queues with SimpleWorker (no fork) to also cut fork+torch-import latency for tiny tools (hash/qr).
- libmagic is re-initialized on every call: storage.sniff_mime_buffer/sniff_mime_file (storage.py:75-86) call module-level magic.from_buffer/from_file, which loads the multi-MB magic DB per invocation — once per upload and once per output file registered (worker._register_outputs, one per output). Build a single magic.Magic(mime=True) at import and reuse under a lock (the libmagic cookie is not thread-safe).
- Failure and cancel paths leak output_dir: run_tool (worker.py) only wipes workdir in finally; output_dir is only created/registered on the SUCCESS path. A ToolError or crash leaves partial files in /data/outputs/<job> untouched until purge_old_jobs rmtrees it 30 days later. Wipe/register output_dir consistently and assert >=1 output on success (a tool that writes to cwd=workdir instead of output_dir currently yields a 'done' job with zero outputs, silently).
- Availability checks are uncached and synchronous on hot paths: every GET /tools (tools.py) and every POST /jobs (jobs.py:136) calls tool.available(); for AI tools that means _ollama.is_available()+has_model() = two httpx GET /api/tags round-trips PER tool (multi_doc_qa.available). Rendering the tool list when Ollama is slow/down blocks ~2s per AI tool. Cache availability with a short TTL and reuse one httpx.Client.
- Downloads require the Authorization bearer header (files.py:97 download_file depends on get_current_user), so a browser cannot follow a plain <a href download> link and there is no Range/streaming/ETag story beyond what FileResponse gives. Add short-lived signed one-time download tokens (query-param) so the SPA can hand the URL straight to the browser, and set Accept-Ranges/caching headers for large outputs.

#### Job queue and lifecycle (queueing.py, routes/jobs.py, worker.run_tool)  ·  `job-queue`  ·  _concern_

- **Edge cases:**
    - File double-claim race: _validate_files checks f.job_id is None then sets it, with no row lock. Two concurrent POST /jobs referencing the same file_id can both pass the check before either commits (jobs.py:96-99, 153-155); there is no unique constraint on File.job_id, so both jobs 'own' the same file. Use SELECT ... FOR UPDATE or a partial unique index.
    - Cancel vs start race clobbers state: cancel_job only proceeds if status=='queued' (jobs.py:209). If cancel reads 'queued' while the worker concurrently flips to 'running', cancel overwrites status='canceled' but RQ's cancel of an already-started horse is a no-op, so the subprocess keeps running and run_tool ends by unconditionally setting status='done' (worker.py:166) — final state contradicts the user's cancel.
    - RQ job_timeout and per-subprocess run_cmd timeout are BOTH job_timeout_seconds (1800). A multi-step tool can keep each subprocess under 1800s yet exceed 1800s wall-clock; RQ then SIGKILLs the horse. On SIGKILL the finally-block never runs (workdir leaks), the DB stays 'running', and the 'Timeout' branch in run_tool (worker.py:176) never fires because a horse SIGKILL is not a Python exception.
    - Enqueue-after-commit gap (see cross_cutting): job persisted queued before enqueue; crash or transient Redis failure between the commits strands the job. The except path (jobs.py:160) only covers a synchronous enqueue exception, not a crash.
    - No per-user concurrency cap: rate limit is 60/min on create, so one user can enqueue 60 heavy transcode/RAG jobs in a burst and starve the shared 'heavy' queue for everyone (no fairness/priority).
    - params with an empty properties schema and no additionalProperties:false accept arbitrary extra keys (jsonschema.validate, jobs.py:146); unvalidated keys are stored in JSONB and passed through to ctx.params.
- **Optimizations:**
    - Two commits per create (files, then rq_job_id) — jobs.py:155 and :159; collapse to one or enqueue-then-commit.
    - Use SimpleWorker/threaded worker for the 'default' queue of cheap tools to avoid a fork per hash/qr job.
    - Replace client polling of GET /jobs/{id} with SSE/websocket fed from Redis pub/sub on progress (worker._set_progress already writes each tick to the DB — every poll is an extra DB round-trip per client).
- **Improvements:**
    - Wire an RQ on_failure/on_stopped callback so horse death/timeout still transitions the DB row to error.
    - Add the reaper described in cross_cutting.
    - Make cancel able to stop a running job (signal the horse / process group) and guard run_tool's terminal transitions with a status re-check (don't set 'done' over 'canceled').
- **Broader support:**
    - Expose queue position / ETA (RQ Queue index) in JobOut.
    - Support job dependencies/chaining (RQ depends_on) for multi-tool pipelines.
    - Allow re-run/retry of a failed job reusing the same inputs.

#### Upload and storage (storage.py, routes/files.py)  ·  `upload-storage`  ·  _concern_

- **Edge cases:**
    - No disk quota enforcement: save_upload only checks per-file max_upload_bytes (storage.py:108). disk_used_bytes() exists but is used only for admin stats — a user can fill the disk with many sub-512MB uploads (DoS). No per-user quota and no free-space precheck.
    - safe_suffix loses compound extensions: Path('x.tar.gz').suffix == '.gz' (storage.py:70-72), so a tar.gz is stored as <uuid>.gz. Extension gating in jobs uses orig_name (fine) but any tool inferring type from the stored path suffix sees .gz not .tar.gz.
    - Extension spoofing passes for non-archive tools: _validate_files only cross-checks sniffed mime vs extension for ARCHIVE_MIMES (jobs.py:111-119). Renaming evil.bin -> doc.pdf passes the extension gate for every non-archive tool; only the tool engine catches it later.
    - ClamAV StreamMaxLength: clamav_scan streams the whole file with a 120s socket timeout (storage.py:142). clamd's default StreamMaxLength (~25MB) makes it reply with a size-limit error that is neither OK nor FOUND -> RuntimeError -> 503 'scanner unavailable, upload rejected' (files.py:69-75). Every file above clamd's limit becomes un-uploadable when clamav_enabled, and a 512MB scan can exceed 120s on 9p.
    - mime sniff only sees the first 8192 bytes (SNIFF_BYTES) — container formats with trailing metadata (e.g. mp4 with moov at end) can sniff to a generic type.
    - path.relative_to(settings.data_dir) in worker._register_outputs (worker.py:103) raises ValueError if data_dir has a trailing slash / symlink / case-mismatch vs the resolved output path (a real risk on /mnt/c 9p, which is case-insensitive).
- **Optimizations:**
    - Reuse one libmagic handle (see cross_cutting) instead of per-call load.
    - disk_used_bytes() walks the ENTIRE data tree with a stat per file on every admin /stats call (storage.py:129-137) — O(all files), very slow on 9p; track a running counter or cache with TTL.
    - 1MB CHUNK_SIZE causes many small writes on the 9p /mnt/c mount; a 4-8MB buffer cuts 9p round-trips.
    - sniff_mime after write re-opens the file from disk; sniff from the in-memory head buffer that save_upload already captured.
- **Improvements:**
    - Enforce per-user and global storage quotas plus a free-space precheck before streaming.
    - Cross-check sniffed mime against tool.accepts for ALL tools, not just archives.
    - Detect and gracefully reject clamd size-limit / partial responses distinctly from 'scanner down'.
- **Broader support:**
    - Support resumable/chunked (tus) uploads for large media over flaky links.
    - Support pulling from a URL (server-side fetch) as an input source.
    - Deduplicate identical uploads by content hash to save disk.

#### Retention and cleanup (cleanup.py, main.retention_loop)  ·  `retention-cleanup`  ·  _concern_

- **Edge cases:**
    - Orphan uploads never expire when file_retention_hours=0: with retention off, upload rows get expires_at=None (files.py:78) and purge_expired_files skips NULL expiries; an upload never attached to a job (user uploads then abandons) is unreachable by purge_old_jobs (which only touches files with a job_id) -> unbounded growth.
    - purge_old_jobs detaches inputs (f.job_id=None, cleanup.py:53) turning a 30-day-old job's uploads back into orphan uploads carrying a long-past expires_at — caught next expired pass only if retention>0, leaked forever if retention=0.
    - Stuck 'running' jobs (from worker death) pin their tmp dir forever: purge_orphan_tmp keeps any tmp whose job is still ACTIVE (cleanup.py:75), so a job stuck 'running' is never cleaned — compounds the reaper gap.
    - Multi-replica race: retention_loop runs in-process in every API replica with no advisory lock; concurrent passes double-delete files (delete_stored_file is missing_ok, but two db.delete of the same row can error the whole batch commit).
    - purge_expired_files loads ALL expired rows with .all() and commits once (cleanup.py:26-36) — one failing delete rolls back the entire batch; no batching/limit.
    - shutil.rmtree(..., ignore_errors=True) on outputs (cleanup.py:54) silently leaves files behind on a lock/permission error (plausible on Windows/9p) with no log -> silent disk leak.
- **Optimizations:**
    - Bulk SQL DELETE WHERE expires_at < now after unlinking, instead of ORM per-row.
    - Move cleanup to a dedicated scheduled worker (RQ scheduler/cron container) so retention still runs when the API is down and doesn't share the event loop.
- **Improvements:**
    - Add pg_advisory_lock so exactly one cleanup pass runs across replicas.
    - Fold the stuck-job reaper into run_cleanup (age-out running/queued).
    - Log rmtree residue and expired-orphan uploads.
- **Broader support:**
    - Per-user or per-tool retention overrides.
    - A soft-delete / trash window before permanent purge.

#### Auth and JWT (auth.py, routes/auth.py)  ·  `auth-jwt`  ·  _concern_

- **Edge cases:**
    - /auth/login is NOT rate limited: unlike upload_file and create_job, the login handler (routes/auth.py:19) has no @limiter.limit decorator, so password brute-force is unthrottled at the app layer. Combined with the proxy issue below, this is a real online-brute-force gap.
    - No token revocation on password change: HS256 tokens live 7 days (auth.py:19) with no jti/token-version. patch_user changing a password (admin.py:86) does NOT invalidate outstanding tokens — a leaked token stays valid until exp. (Disabling or deleting a user IS effective, because get_current_user re-loads the row each request, auth.py:75-83.)
    - bcrypt silently truncates to 72 bytes (auth.py:27,32): two passwords identical in their first 72 bytes are equivalent, and the [:72] byte slice can cut mid-UTF8-codepoint; never surfaced to the user.
    - Weak password policy: AdminUserCreate/Patch enforce only min_length=4 (schemas.py:37,42).
    - Username uniqueness is case-sensitive (String(64) unique, models.py:23) — 'Admin' and 'admin' are distinct accounts; login is exact-match, enabling confusing look-alikes.
    - No nbf/aud/iss claims; a single shared secret both signs tokens and is used by the rate limiter to decode them (ratelimit.py:17).
- **Optimizations:**
    - get_current_user does a PK db.get(User) on every authenticated request to check 'disabled' — cheap, but could be a short-TTL cache if revocation latency is acceptable.
- **Improvements:**
    - Add a token-version/jti column bumped on password change and logout to enable revocation; consider shorter access tokens + refresh tokens.
    - Explicitly rate-limit /auth/login per-username and per-IP and add failed-attempt lockout/backoff.
    - Pre-hash (e.g. sha256) before bcrypt or reject >72-byte passwords to avoid silent truncation; raise the min length.
- **Broader support:**
    - Optional TOTP/2FA and API keys for programmatic access.
    - OIDC/reverse-proxy header auth for SSO deployments.

#### Rate limiting (ratelimit.py)  ·  `rate-limiting`  ·  _concern_

- **Edge cases:**
    - Behind nginx, get_remote_address returns the PROXY IP for all anonymous traffic: slowapi's key_func (ratelimit.py:22) reads request.client.host and does NOT parse X-Forwarded-For. So every unauthenticated caller shares ONE bucket keyed on the proxy IP — one abuser can exhaust the anonymous limit and DoS all logins, and per-attacker limiting is meaningless. Needs a trusted-proxy / X-Forwarded-For (or nginx X-Real-IP) key.
    - swallow_errors=True (ratelimit.py:28) fails open: if Redis is briefly down, rate limiting is silently disabled — an availability/DoS window.
    - One global 60/min limit is applied identically to a cheap GET and to create_job; a user can still enqueue 60 heavy jobs/minute.
    - Expired-but-well-signed tokens fall back to IP keying (jwt.decode verifies exp -> InvalidTokenError -> get_remote_address), lumping that user in with the shared proxy bucket.
- **Optimizations:**
    - Decoding the JWT on every request just to derive the key duplicates work already done by get_current_user; could reuse the parsed identity via request.state.
- **Improvements:**
    - Honor X-Forwarded-For with a trusted-hops config (or key on the nginx-set X-Real-IP header).
    - Add stricter, separate limits for /auth/login and POST /jobs vs. read endpoints.
    - Emit Retry-After / X-RateLimit-* headers (the custom 429 handler at main.py:87 currently returns only a bare detail).
- **Broader support:**
    - Per-tool or per-queue quotas (e.g. N heavy jobs per hour).
    - Admin-configurable limits without a restart.

#### Output filename handling (worker._rename_outputs, _nice_stem)  ·  `output-filename`  ·  _concern_

- **Edge cases:**
    - Non-ASCII names collapse to 'output': _nice_stem strips to [A-Za-z0-9._-] (worker.py:57-62), so a Chinese/Cyrillic/RTL-named upload always downloads as 'output.pdf' — the friendly-name feature silently fails for every non-Latin filename.
    - Collision leaves ugly uuid names: if two inputs sanitize to the same nice stem (e.g. report.pdf and report.docx both -> 'report'), the 'not target.exists()' guard (worker.py:82) SKIPS the second rename, so that output keeps its raw uuid name and _register_outputs stores that ugly name as orig_name (worker.py:104).
    - Loose startswith matching: an output whose name coincidentally begins with the wrong input's uuid stem (worker.py:80) is renamed with the wrong original name; the break after the first match means only one mapping is ever applied.
    - Rename failures are swallowed (except OSError: pass, worker.py:85) — plausible on 9p/Windows file locks — leaving the uuid name, which then becomes the download filename.
    - _register_outputs registers EVERY file under output_dir recursively (worker.py:96): a tool that writes intermediate/junk files into output_dir (instead of workdir) exposes them all as downloadable outputs.
- **Optimizations:**
    - Build the mapping once and rename in a single pass (already O(inputs*outputs)); fine, but skip the rglob when there are no outputs.
- **Improvements:**
    - Preserve Unicode: keep a UTF-8 nice stem (strip only path-dangerous chars) and set Content-Disposition filename* (RFC 5987) in FileResponse for correct browser naming.
    - Deduplicate deterministically (append -1/-2) instead of leaving a uuid name on collision.
    - Validate that outputs live only where the tool intends (e.g. a manifest of declared outputs) rather than registering everything under output_dir.
- **Broader support:**
    - Let tools declare canonical output names/labels in a manifest instead of relying on stem-rename heuristics.
    - Offer a single-file zip download when a job emits many outputs.

#### SPA serving (main.py optional WEB_DIST block)  ·  `spa-serving`  ·  _concern_

- **Edge cases:**
    - Prefix-based traversal check is weak: spa() does candidate.startswith(_WEB_DIST) (main.py:139). This is a string prefix, so if _WEB_DIST='/srv/web', a normpath result of '/srv/web-evil/secret' also passes and gets served — a sibling-directory escape. Use os.path.commonpath or append os.sep before comparing.
    - Windows path-separator mixing: full_path from the URL uses forward slashes while os.path.normpath on Windows uses backslashes, so the normalization/prefix logic differs by platform (this block is dev-only; prod serves via nginx).
    - The catch-all GET /{full_path:path} returns index.html for anything not starting with 'api/' — fine for client routing, but it also means a missing static asset returns 200+index.html instead of 404.
- **Optimizations:**
    - StaticFiles is only mounted for /assets; other static roots (favicon, manifest) fall through to the per-request FileResponse path.
- **Improvements:**
    - Replace the prefix check with commonpath-based containment.
    - Add cache-control/ETag headers for hashed assets.
- **Broader support:**
    - Optional gzip/br precompressed asset serving when nginx is not in front.

#### DB schema and session (models.py, db.py)  ·  `db-schema`  ·  _concern_

- **Edge cases:**
    - No index on File.expires_at (models.py:67): purge_expired_files filters expires_at < now hourly -> full table scan that worsens as files accumulate. Same for Job.created_at (purge_old_jobs and list_jobs order by it) — only Job.status and Job.user_id are indexed, so list_jobs' (user_id + order-by created_at desc) has no covering composite index.
    - No unique constraint preventing a File being claimed by two jobs (enables the create-job race noted under job-queue).
    - create_all only, no migrations (db.py:25-29): any schema change (e.g. adding a token-version column) requires manual DDL; create_all will not ALTER existing tables. No Alembic.
    - Python-side default=False for is_admin/disabled (models.py:25-26) is not a server_default; rows inserted via raw SQL would violate NOT NULL. JSONB params default=dict is likewise app-side.
    - JSONB/Uuid(as_uuid) assume Postgres; a sqlite dev DB (plausible for the local WSL no-Docker run) would mishandle these types.
- **Optimizations:**
    - Add indexes: files(expires_at), files(user_id), files(job_id, kind), jobs(user_id, created_at desc).
    - expire_on_commit=False (db.py:22) is a good choice for the worker's repeated commit-per-progress pattern; keep, but be aware create_job relies on the explicit db.refresh(job) before job_to_schema to see freshly attached files.
    - Pool is size=5/overflow=10 per process; the retention thread plus request handlers share the API pool — size it against expected concurrency.
- **Improvements:**
    - Introduce Alembic migrations before the first schema evolution.
    - Add server_default for the boolean/JSONB columns.
    - Add a partial unique index or CHECK to prevent double file-claim.
- **Broader support:**
    - Add a jobs(status, created_at) index to support future admin filtering by status.
    - pgvector column to cache RAG embeddings across jobs.

#### Worker subprocess timeout and kill (base.run_cmd, worker.run_tool)  ·  `worker-subprocess`  ·  _concern_

- **Edge cases:**
    - Timeout kills only the direct child, not the process group: subprocess.run(timeout=...) SIGKILLs the immediate child on TimeoutExpired (base.py:69), but ffmpeg/libreoffice/pandoc spawn grandchildren that keep running as orphans — CPU/disk leak. Use start_new_session=True + os.killpg.
    - capture_output=True buffers ALL stdout/stderr in RAM (base.py:62-63): a 30-minute ffmpeg transcode streams many MB to stderr, all held in the worker's memory until completion, even though only the last 500 chars are used on error (base.py:75). Stream verbose output to a temp file or DEVNULL.
    - Per-subprocess timeout defaults to the FULL job_timeout (base.py:59-60) and equals the RQ job_timeout, so the graceful ToolError-timeout path is usually pre-empted by an RQ horse SIGKILL at the same 1800s wall-clock (see job-queue) -> stuck 'running' + leaked workdir with no error recorded.
    - No memory/CPU sandbox: a decompression bomb (e.g. a 50000x50000 PNG into image_upscale) can OOM-kill the worker; there is no RLIMIT_AS/ulimit/cgroup. (Archive zip-bombs are handled per the test notes, but image/PDF pixel bombs are a separate vector.)
    - cwd=workdir (base.py:61) but tools must write outputs to ctx.output_dir explicitly; a tool that writes a relative path expecting cwd=output_dir drops files into workdir, which finally-wipes them -> a 'done' job with zero outputs and no warning.
- **Optimizations:**
    - Preload heavy models in the parent before Worker.work() (or use SimpleWorker) so forked horses inherit them (see cross_cutting) — biggest win for transcribe.
    - Add -threads / nice / ionice knobs to bound CPU and I/O contention on the shared CPU-only host.
    - Redirect subprocess stderr to a rolling temp file so long runs don't grow worker RSS.
- **Improvements:**
    - start_new_session=True and killpg on timeout AND on cancel so no orphaned encoders survive.
    - Set RLIMIT_AS/RLIMIT_CPU on the child (preexec_fn) and consider bubblewrap/nsjail + a non-root uid + no-network for offline tools.
    - Assert >=1 output on success and wipe output_dir on failure (see cross_cutting).
- **Broader support:**
    - A per-tool timeout override (transcribe of a 3h podcast needs more than a 30s hash).
    - Per-tool resource profiles (mem/cpu caps) declared on the Tool class.

#### AI model lifecycle and RAG (transcribe.py, _ollama.py, multi_doc_qa.py)  ·  `ai-model-lifecycle`  ·  _gpu-gated_

- **Edge cases:**
    - RAG issues up to 201 sequential blocking HTTP calls: multi_doc_qa embeds each chunk in a Python for-loop (multi_doc_qa.py:82-84), one _ollama.embed per chunk up to _MAX_CHUNKS=200, plus the query — each a fresh httpx.post with no connection reuse. On CPU-only nomic-embed-text this is minutes of serial round-trips.
    - Whisper model reloaded every job: _MODEL global (transcribe.py:11) lives only in the forked horse, so the 'cached once per worker' docstring is false under RQ's default forking worker — every transcription reloads weights from disk.
    - Availability double-ping: multi_doc_qa.available() calls is_available()+has_model() = two GET /api/tags (2s timeout each) on every /tools render and every create_job (_ollama.py:12,22).
    - RAG chunking is character-based with no token budget: 200 chunks of 1500 chars glued into one prompt (multi_doc_qa.py:92) can blow past qwen's context window -> silent truncation or an Ollama error.
    - extract_text caps at 200k chars per doc (multi_doc_qa.py:73) then chunking caps at 200 chunks — large documents are silently truncated with only a terse note.
- **Optimizations:**
    - Batch embeddings (Ollama /api/embed accepts arrays) or fire them concurrently over one reused httpx.Client with keep-alive.
    - Cache embeddings by content hash so re-asking over the same docs skips re-embedding.
    - Cache _ollama availability/has_model with a short TTL instead of pinging per request.
    - Reuse a module-level httpx.Client in _ollama (every embed/chat/is_available currently opens a new connection).
- **Improvements:**
    - Preload whisper in the worker parent (or SimpleWorker) so it is actually cached.
    - Token-count the assembled RAG context and trim to the model's context window before calling chat.
    - Stream Ollama chat responses to report progress and lower memory.
- **Broader support:**
    - Persist embeddings in pgvector for cross-job reuse.
    - Expose whisper beam_size/vad params and speaker diarization; support word-level timestamps.
    - Support larger whisper models / GPU when available via config.

#### Health and observability (main.healthz)  ·  `health-observability`  ·  _concern_

- **Edge cases:**
    - healthz checks DB + Redis only (main.py:111-122) — it does NOT check that any RQ worker is alive/consuming. With every worker dead, jobs pile up 'queued' indefinitely while /healthz returns 200 (false-healthy).
    - No queue-depth/backlog threshold in the health signal; a runaway backlog is invisible to orchestration probes.
    - No request-id / structured logging correlation across the API and worker, making a single job's lifecycle hard to trace.
- **Optimizations:**
    - healthz opens a fresh engine.connect() + SELECT 1 and a redis ping on every probe; fine, but a frequent k8s liveness probe adds steady DB/Redis load — consider a lightweight cached readiness split from liveness.
- **Improvements:**
    - Add worker-liveness (rq.Worker.all(connection)) and queue-depth to a /readyz, distinct from a cheap /livez.
    - Add a Prometheus /metrics endpoint (queue depths, job durations, failure counts, disk used).
    - Attach a request id to logs and propagate it into the job row for end-to-end tracing.
- **Broader support:**
    - Structured JSON logs for ingestion.
    - Optional alerting hook when a queue backlog or failure rate crosses a threshold.


### Frontend & UX

**Cross-cutting for this group:**

- No global ErrorBoundary anywhere (App.tsx) — an uncaught render error in any page white-screens the entire SPA with no recovery.
- Everything is poll-based (Jobs 2s) or request/response; there is no SSE/WebSocket layer, so real-time job progress costs repeated full-list fetches. A single push channel would cut load and give sub-second progress on heavy CPU/AI jobs.
- No shared data cache (no React Query/SWR): listTools() is fetched independently by Dashboard and by every ToolPage mount, and Admin/Jobs each own their fetch — repeated network and no dedup/invalidation.
- No route-level code splitting: Admin and the iframe-heavy QuickTools ship in the main bundle for all users; React.lazy per route would shrink initial load.
- Accessibility gaps are systemic: dynamic error/status/reject messages are plain <p>/<div> without aria-live; there's no focus management or title update on route change, no skip link, and validation errors hide in native `title` tooltips (invisible on touch).
- Theme FOUC affects the whole app (no pre-hydration theme script in index.html), and several surfaces bypass theme tokens (auth CenteredSpinner hardcoded neutral-950/emerald-500).
- No i18n and no RTL support — all labels/status strings are hardcoded English; only dates go through toLocaleString.
- Session-expiry UX is uniformly harsh: any 401 does a full-page window.location redirect that drops SPA state and forgets the user's location; a soft router-based flow with return-to-path would be a broad win.
- Large-file handling is weak end-to-end on a suite built for media/AI: uploads have no progress and buffer, downloads buffer the whole blob in memory — both risk apparent hangs or OOM on big inputs/outputs.
- No offline/connectivity awareness: ApiError(0,'Network error') is produced per-call but there's no global banner or auto-retry, and the Jobs poller actively freezes after one failed request.

#### Drop-to-suggest (Dashboard smart drop zone)  ·  `drop-to-suggest`  ·  _concern_

- **Edge cases:**
    - Dashboard.tsx extsOf() takes only the LAST dot segment: 'archive.tar.gz' -> '.gz', so a tool that accepts '.tar.gz' or '.tar' is never suggested; multi-part extensions are unsupported.
    - Files with NO extension (Dockerfile, README, a dropped folder) add nothing to the ext set, so only accepts.length===0 (any-file) tools are suggested even if a specific tool would apply.
    - suggest() filters out `!t.available` tools (line 43), so dropping a file whose only matching tool is GPU-gated shows 'No tools match that file type.' — hides the tool entirely instead of showing it as needs-setup.
    - suggest() only checks `min_files > 0`, not min_files vs actual count: dropping ONE pdf suggests pdf-merge (min_files=2); the user reaches ToolPage only to hit 'needs at least 2 files'.
    - No window-level dragover/drop preventDefault: dropping a file anywhere OUTSIDE the dashed zone triggers the browser default (navigates away / opens the file), losing the SPA and any state.
    - drop.files.map(f=>f.name).join(', ') at line 127 is unbounded — dropping 200 files renders a massive comma string with no truncation or count cap.
    - Preset File objects are passed via react-router `location.state`; a full page reload on /tool/:slug loses them silently (presetFiles undefined) and the file list empties with no notice.
    - Trailing-dot filenames ('report.') produce a junk '.' entry in the ext set via parts.pop().
- **Optimizations:**
    - Dashboard fetches listTools() on mount and ToolPage fetches the FULL list again to find one slug — no shared cache; every dashboard->tool navigation re-downloads all ~47 tool schemas. Lift tools into a context/React-Query cache or add a /tools/:slug endpoint.
    - Memoize extsOf/suggest matching; currently recomputed on each drop but fine — bigger win is caching the tools list.
- **Improvements:**
    - Show GPU-gated matches as disabled 'needs setup' chips in suggestions rather than filtering them out, so users learn the capability exists.
    - Filter suggestions by whether the dropped file COUNT satisfies min_files, or annotate 'needs N files'.
    - Add a global drag overlay (window dragenter/drop preventDefault) so a stray drop never navigates the browser away.
    - Cap the filename list in the suggestion header ('file1.pdf, file2.pdf +8 more').
    - Persist preset files through reload (e.g. keep them in memory keyed by a nav id, or re-prompt) instead of vanishing.
- **Broader support:**
    - Match on full multi-part extensions and optionally MIME type, not just the last segment.
    - Support dropping a directory (webkitGetAsEntry) to enumerate contained files.

#### Schema-driven params form  ·  `schema-driven-forms`  ·  _concern_

- **Edge cases:**
    - ParamsForm.tsx renders only enum/boolean/number/integer/multiline/text. `type:'array'` params fall through to a plain text input, sending a string where the backend expects a list (e.g. page-range lists).
    - minimum/maximum are set as HTML min/max attrs (lines 92-93) but NEVER validated on submit — ToolPage.tsx validationError only checks `required`. A value below minimum or above maximum passes client validation and relies on a backend 422.
    - pattern, minLength, maxLength, exclusiveMinimum/Maximum, multipleOf are all ignored — no client enforcement.
    - integer field uses parseInt: typing '1.5' silently becomes 1, '1e3' becomes 1, with the displayed value snapping — data changes with no feedback.
    - Optional enum select: the empty '—' option only renders while value===undefined (line 52), so once a value is picked the user can NEVER clear an optional enum back to unset.
    - string formats (date, email, uri, color) all render as generic text — no date/color picker, no validation.
    - Required-field check treats boolean `false` and number `0` as present (correct for 0, but a required checkbox is 'satisfied' while unchecked).
    - Only the FIRST validation error is surfaced (validationError returns early); with several missing required fields the user fixes them one at a time.
- **Optimizations:**
    - Field component re-created inline per render; fine at this scale but could be memoized for tools with many params.
- **Improvements:**
    - Enforce min/max/pattern/length client-side and show inline per-field errors instead of a single aggregate string on the Run button's native `title` (invisible on touch devices).
    - Add a clearable control for optional enums (persistent '—' option or a reset affordance).
    - Surface ALL validation errors at once, anchored to their fields, with aria-live for screen readers.
    - Add units/help affordances (slider for bounded ints, stepper) and show default-value hints.
- **Broader support:**
    - Support array params (repeatable inputs / tag entry), string formats (date, color, uri), and dependent/conditional fields (JSON-Schema if/then or oneOf).
    - Support enum labels distinct from values (title per option) so slugs aren't shown raw.

#### Job list + polling  ·  `job-polling`  ·  _concern_

- **Edge cases:**
    - Polling HALTS on the first failed poll: Jobs.tsx re-arms the 2s timer via an effect keyed on [jobs, load]. On a network error load() sets `error` but does NOT change `jobs`, so the effect never re-runs and no new timeout is scheduled — a running job then appears frozen until the user manually reloads. Live updates never resume after one transient failure.
    - List is capped at PAGE_SIZE=100 with offset fixed at 0 and no pager, while `total` is displayed — jobs beyond 100 are unreachable in the UI.
    - Polling ignores tab visibility: it keeps hitting /jobs every 2s even when the tab is backgrounded/hidden (no Page Visibility check), wasting battery and requests.
    - A newly created job is highlighted via ?highlight=, but if it isn't in the first 100 (unusual ordering) it's never shown/scrolled to; the highlight also persists in the URL indefinitely.
    - No auto-scroll to the highlighted row — in a long list the just-created job can be off-screen.
- **Optimizations:**
    - Every 2s poll re-fetches 100 full Job objects (including nested input/output FileInfo) with no ETag/delta/If-None-Match — replace with SSE/WebSocket push for progress, or at minimum only poll the ids that are active.
    - Full load() after every cancel/delete refetches the whole list, causing table flicker and scroll-position loss; use optimistic local updates.
    - Pause polling on document.hidden and back off on error instead of a fixed 2s.
- **Improvements:**
    - Add exponential-backoff retry + a 'reconnecting…' banner so a dropped poll self-heals instead of freezing.
    - Add pagination / infinite scroll to reach jobs past the first 100.
    - Add filters (by status/tool) and a search box for large job histories.
    - Confirm before Cancel (only Delete currently confirms), and make actions optimistic.
- **Broader support:**
    - Server-Sent Events endpoint for real-time progress would remove polling entirely and give sub-second progress on heavy media/AI jobs.
    - Bulk actions (select-all, delete completed, cancel all queued).

#### JobRow rendering  ·  `job-row`  ·  _concern_

- **Edge cases:**
    - JobRow.tsx shows job.tool RAW (the slug e.g. 'pdf-merge') as the tool name instead of the friendly ToolInfo.name ('Merge PDFs') — the Jobs table never resolves slugs to display names.
    - Duration shows '-' for the entire run of a job because formatDuration() needs both started_at AND finished_at (format.ts line 32); there is no live elapsed timer for running jobs.
    - A 'done' job with zero output_files renders only a Delete button and no indication of what happened.
    - Long error text is CSS-truncated (max-w-56) with the full text only in a native `title` tooltip — inaccessible on touch and to screen readers.
- **Optimizations:**
    - Progress bar transition duration-500 with 2s polling means visible stepping; SSE would smooth it.
- **Improvements:**
    - Resolve job.tool to the friendly name (needs the tools list in scope / a lookup map).
    - Show a live elapsed timer (now - started_at) for running jobs.
    - Add result previews (image thumbnail, PDF first page, audio player) inline instead of download-only.
    - Expandable full error detail (click-to-expand) rather than truncate+title.
- **Broader support:**
    - 'Download all as zip' when a job emits multiple outputs (each is currently a separate button).
    - Re-run / duplicate-job action prefilled with the same params.

#### Theme (light/dark/system)  ·  `theme`  ·  _concern_

- **Edge cases:**
    - FOUC: index.html has no inline pre-hydration script and main.tsx renders before theme.tsx's useEffect calls apply(); the data-theme attribute is unset until after first paint, so a dark-mode user sees a light flash on every load.
    - The header toggle only flips light<->dark (theme.tsx toggle, Layout.tsx) — there is NO UI to return to 'system'; once toggled, choice is pinned to explicit light/dark and stops following the OS.
    - localStorage.setItem in setChoice is unguarded: in private-mode/storage-disabled browsers the toggle throws and is uncaught.
    - auth.tsx CenteredSpinner uses hardcoded Tailwind colors (bg-neutral-950, border-emerald-500) instead of theme tokens, so the initial auth-loading screen is always a black page with a green spinner regardless of light theme.
- **Optimizations:**
    - Move theme resolution to a tiny inline <script> in index.html (read localStorage, set data-theme + colorScheme) to eliminate the flash before the bundle loads.
- **Improvements:**
    - Expose a 3-way theme control (light/dark/system) since the state model already supports 'system'.
    - Wrap localStorage access in try/catch.
    - Re-theme CenteredSpinner with surface/primary tokens.
- **Broader support:**
    - Respect prefers-reduced-motion for the animate-in / pulse / hover-translate transitions used across cards, rows, and the running-status dot.

#### Quick Tools embedding (iframes)  ·  `quick-tools-embedding`  ·  _concern_

- **Edge cases:**
    - QuickTools.tsx builds iframe src as `http://${hostname}:8091..8093` with a hardcoded http:// scheme; if SelfX itself is served over HTTPS these are mixed-content and browsers block them → blank iframes.
    - URLs assume the ports are directly reachable from the client host; behind a reverse proxy/domain that doesn't expose 8091-8093, every embed is broken.
    - No load/error state for the iframe: if a backing service is still starting or down, the user sees the browser's error page and only a static 'may still be starting' tip; cross-origin load failure can't be detected to offer retry.
    - No sandbox attribute on the iframe embedding third-party apps (IT-Tools/CyberChef/Omni-Tools).
- **Optimizations:**
    - Lazy-mount the iframe only when a card is opened (already the case) — but also unmount on Back to free the embedded app's memory.
- **Improvements:**
    - Derive scheme from window.location.protocol (or proxy these under same-origin paths) so it works over TLS.
    - Add a loading spinner + timeout->‘open in new tab’ fallback around the iframe.
    - Add sandbox/allow attributes scoped to what each embedded tool needs.
    - Health-check each service and badge cards as up/starting/down.
- **Broader support:**
    - Make the embedded-app list configurable (env / backend-provided) instead of a hardcoded 3-entry array, so operators can add their own local tools.

#### Auth flow (login, session, 401 handling)  ·  `auth-flow`  ·  _concern_

- **Edge cases:**
    - Mid-session expiry does a HARD redirect: api.ts handleUnauthorized() calls window.location.assign('/login') (full reload), discarding any in-progress form/params on ToolPage instead of a soft router navigate.
    - The 401 redirect does NOT capture the current path as `from`, so after re-login Login.tsx sees state.from===undefined and always lands the user on '/' — they lose where they were (RequireAuth's from-tracking is bypassed).
    - JWT is never decoded, so the app can't proactively warn about or refresh an expiring session; it only reacts to a 401 after a failed request.
    - Token lives in localStorage under 'selfx_token' — readable by any injected script (XSS-exposed); no httpOnly cookie option.
    - Parallel API calls that all 401 each invoke handleUnauthorized -> multiple location.assign redirects (harmless but redundant).
    - No caps-lock/show-password affordance on the login form.
- **Optimizations:**
    - Use router navigation for 401 instead of full page reload to avoid re-downloading the whole bundle on every session expiry.
- **Improvements:**
    - Preserve and restore the pre-401 location for post-login return.
    - Decode token exp to show a 'session expiring' warning and/or silent refresh.
    - Add a 'show password' toggle and surface lockout/rate-limit messaging distinctly.
    - Consider refresh-token + short-lived access token, or an httpOnly cookie mode.
- **Broader support:**
    - Optional 'remember me' vs session-only storage; multi-tab logout sync via the storage event (logging out in one tab should clear others).

#### Downloads  ·  `downloads`  ·  _concern_

- **Edge cases:**
    - downloadFile() in api.ts loads the ENTIRE output into a Blob in memory (res.blob()) before saving; for large media/AI outputs (hundreds of MB–GB on this suite) this can OOM the browser tab.
    - No download progress: the fetch buffers silently, so a big output looks frozen (no spinner/percentage) until the blob resolves and the save dialog appears.
    - URL.revokeObjectURL(url) is called synchronously right after a.click() (lines 159-160); some browsers race and can cancel large-blob saves that haven't committed — safer to defer revoke.
    - 401 during download triggers handleUnauthorized full-reload mid-download.
    - Auth is header-based (Bearer), which is exactly why a plain <a href download> can't be used — forcing the in-memory blob approach.
- **Optimizations:**
    - Add a short-lived signed/tokenized download URL (query param) so the browser can stream the file natively to disk without buffering it in JS memory.
    - Stream via ReadableStream + File System Access API where available to avoid full-memory buffering.
- **Improvements:**
    - Show per-download progress and a disabled/spinner state on the download button.
    - Defer URL.revokeObjectURL via setTimeout to dodge the early-revoke race.
    - Offer 'download all outputs as zip' for multi-output jobs.
- **Broader support:**
    - Honor server Content-Disposition filename when present rather than always forcing orig_name.

#### File upload (FileDrop + ToolPage upload loop)  ·  `file-upload`  ·  _concern_

- **Edge cases:**
    - ToolPage.tsx uploads files strictly sequentially (for-loop awaiting each uploadFile) — slow for multi-file tools; and there is NO upload progress (fetch+FormData has no progress events), so a 2GB video shows a frozen 'Uploading 1/1'.
    - Partial-failure orphans: if file 2 of 3 fails to upload, files 1's upload already succeeded server-side but is never used (no job created) and never cleaned up; retry re-uploads everything, and the one-file-per-job rule means the orphans just consume disk.
    - FileDrop matches by filename extension only (matchesAccepts) — a mislabeled 'x.pdf' passes to the backend; a valid file with no/uppercase-odd extension may be wrongly rejected.
    - Single-file mode silently keeps only accepted[0] and discards extra dropped files WITHOUT listing them as rejected (they matched accepts) — user drops 3, sees 1, no message.
    - For multi_file tools where ToolPage explicitly says 'order matters', FileDrop offers NO reorder — only add/remove — so correcting merge order means removing and re-adding files in sequence.
    - No client-side size or empty-file (0-byte) pre-check; the known backend 422 for empty files only surfaces after a full upload attempt.
    - Duplicate suppression is by name+size, so two genuinely different same-size files with the same name drop the second silently.
    - onDragLeave has no enter/leave counter, so dragging over child elements flickers the dragOver highlight.
- **Optimizations:**
    - Upload files in parallel (Promise.all) since uploads are independent.
    - Switch to XHR/upload with progress events (or fetch + ReadableStream) to show real upload percentage for large media inputs.
    - Pre-validate size against a known max before uploading to fail fast instead of after a long transfer.
- **Improvements:**
    - Add drag-to-reorder for order-sensitive multi-file tools.
    - Report ignored files in single-file mode.
    - Clean up / reuse already-uploaded file ids on partial failure and retry.
    - Give rejected/skip messages aria-live so screen readers announce them.
- **Broader support:**
    - Paste-to-upload (clipboard image), and directory upload for batch tools.

#### Tool discovery & navigation  ·  `tool-discovery-nav`  ·  _concern_

- **Edge cases:**
    - Mobile navigation is broken: Layout.tsx nav is `hidden ... sm:flex` with NO hamburger/drawer fallback, so on phones (<640px) only the logo (Dashboard) is reachable — Jobs, Quick Tools, and Admin have no reachable link.
    - Dashboard search is plain substring on name+description only — no fuzzy match, no category/queue filters, no keyboard navigation of results.
    - No route-level document.title updates or focus management on navigation (screen readers don't announce page changes; no skip-to-content link).
- **Optimizations:**
    - Routes are not code-split: Admin and QuickTools (heavy iframe page) are bundled and loaded for every user including non-admins — use React.lazy + Suspense per route.
    - Shared tools list is re-fetched per page (Dashboard, ToolPage) — introduce a cache (React Query/SWR/context) to avoid repeated /tools downloads.
- **Improvements:**
    - Add a mobile menu (hamburger/drawer) exposing all nav destinations.
    - Add a command palette (Ctrl/Cmd-K) to jump to any tool.
    - Add category filter chips and recently-used/favorites on the dashboard.
    - Add a global ErrorBoundary so a render error in one page doesn't white-screen the whole app.
- **Broader support:**
    - i18n framework (all UI strings and status labels are hardcoded English), and RTL layout support.
    - Global offline/online banner using navigator.onLine + the existing ApiError(0) network path.

#### Admin panel  ·  `admin`  ·  _concern_

- **Edge cases:**
    - Admin.tsx resetPassword uses window.prompt — the new password is typed in cleartext, with no confirmation field and no strength/length check; empty/cancel is the only guard.
    - No 'last admin' protection: revoke-admin and disable are only blocked for isSelf, so an admin can revoke/disable every OTHER admin and lock the instance out of admin access.
    - Only Delete confirms; Disable and Revoke-admin apply instantly with no confirmation.
    - Users table has no pagination — a large user base renders one unbounded list (horizontal scroll on mobile via min-w-[560px]).
    - No client-side password-strength/length rule on Create user.
- **Optimizations:**
    - load() re-fetches stats AND full user list after every single admin action (Promise.all) — could update the single changed row locally.
- **Improvements:**
    - Replace window.prompt with a proper modal (masked input + confirm).
    - Guard against removing the last active admin.
    - Add confirmations for disable/revoke; add loading skeletons while stats/users load.
    - Reuse the shared components/StatusBadge instead of the divergent local StatusBadge duplicated in Admin.tsx (lines 50-70), and extend the shared one to support a count.
- **Broader support:**
    - Per-user quota / disk usage and last-login columns; audit log of admin actions; search/sort on the users table.


