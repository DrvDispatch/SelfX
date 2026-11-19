# Adding a tool to SelfX

Every tool is one Python file in `server/app/tools/`. Drop the file in, rebuild, done:
`app/tools/__init__.py` runs `discover()` at startup, which imports every module in the
package, and the `@register` decorator adds your class to the registry. The API then
lists it under `GET /api/v1/tools`, the frontend auto-renders its form from
`params_schema`, and the worker knows how to run it. **No other file needs editing.**

This walkthrough builds a real tool: `video-thumbnail`, which grabs a single frame
from a video with ffmpeg.

## 1. Create the file

Path: `server/app/tools/video_thumbnail.py` (module name is free-form; the `slug`
field is what identifies the tool).

```python
"""Extract a thumbnail frame from a video with ffmpeg."""
from __future__ import annotations

from .base import Tool, ToolContext
from .registry import register


@register
class VideoThumbnail(Tool):
    slug = "video-thumbnail"
    name = "Video Thumbnail"
    category = "media"
    description = "Grab a single frame from a video as a PNG or JPEG image."
    accepts = [".mp4", ".mkv", ".webm", ".mov", ".avi"]
    multi_file = False
    min_files = 1
    queue = "heavy"
    params_schema = {
        "type": "object",
        "properties": {
            "timestamp": {
                "type": "number",
                "title": "Timestamp (seconds)",
                "description": "Point in the video to capture the frame from.",
                "minimum": 0,
                "default": 1.0,
            },
            "format": {
                "type": "string",
                "title": "Image format",
                "enum": ["png", "jpg"],
                "default": "png",
            },
            "max_width": {
                "type": "integer",
                "title": "Max width (px)",
                "description": "Downscale if wider; aspect ratio is kept.",
                "minimum": 16,
                "maximum": 3840,
                "default": 1280,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        src = ctx.input_paths[0]
        ts = float(ctx.params.get("timestamp", 1.0))
        fmt = ctx.params.get("format", "png")
        width = int(ctx.params.get("max_width", 1280))
        out = ctx.output_dir / f"{src.stem}.{fmt}"

        ctx.progress(0.1, "extracting frame")
        ctx.run_cmd([
            "ffmpeg", "-y",
            "-ss", str(ts),
            "-i", str(src),
            "-frames:v", "1",
            "-vf", f"scale='min({width},iw)':-2",
            str(out),
        ])
        ctx.progress(1.0, "done")
```

## 2. The `Tool` fields, one by one

| Field | Meaning |
|-------|---------|
| `slug` | URL-safe unique id (`POST /jobs {"tool": "video-thumbnail", ...}`). `@register` raises on duplicates. |
| `name` / `description` | Shown on the dashboard tool card. |
| `category` | Dashboard grouping: `pdf`, `documents`, `images`, `media`, `ai`, `utilities`. |
| `accepts` | Allowed input extensions. `[]` means the tool takes no file input (see `qr-generate`). Extension check + MIME sniff happen before your code runs. |
| `multi_file` / `min_files` | `pdf-merge` uses `multi_file=True, min_files=2`; param-only tools use `min_files=0`. |
| `params_schema` | JSON Schema (draft-7 subset). Validated server-side with `jsonschema` before your `run()` is called — inside `run()` you may trust the types. |
| `queue` | `"default"` for quick jobs, `"heavy"` for media/AI (see below). |

### params_schema → form mapping

The frontend renders the form directly from the schema — you never write UI code:

| Schema | Rendered as |
|--------|-------------|
| `"type": "string"` | text input |
| `"type": "string", "format": "multiline"` | textarea |
| `"enum": [...]` | select dropdown |
| `"type": "number"` / `"integer"` (+`minimum`/`maximum`) | number input with min/max |
| `"type": "boolean"` | checkbox |
| `"default"` | pre-filled value |
| `"title"` / `"description"` | label / help text |

### Choosing the queue

The worker consumes `default,heavy` in that order. Put a job on `heavy` when it can
run for minutes or hog CPU/RAM (transcoding, OCR, whisper, LLM calls) so it never
blocks the quick stuff. `video-thumbnail` shells out to ffmpeg on possibly-large
videos → `heavy`.

### The context you get in `run()`

- `ctx.input_paths` — absolute paths of the uploaded files (treat as read-only).
- `ctx.params` — the validated params dict.
- `ctx.workdir` — per-job scratch dir, wiped after the run.
- `ctx.output_dir` — **everything you leave here is registered as a downloadable
  result** when the job finishes. That is the whole output contract.
- `ctx.progress(fraction, message)` — updates the job row; the UI polls it.
- `ctx.run_cmd([...])` — the only sanctioned way to call external binaries: list
  args, `shell=False`, `cwd=workdir`, timeout, raises `ToolError` with the stderr
  tail on failure. Never interpolate user strings into flags — user-controlled
  values may only appear as file paths or as schema-validated numbers/enums
  (exactly what `timestamp`, `format`, `max_width` are above).

On unrecoverable problems raise `ToolError("user-safe message")` — it becomes the
job's `error` field. Raw exceptions are caught too, but users then get a generic
message (the traceback goes to the logs only).

### Optional: `available()`

If your tool depends on something that may be down or unconfigured, override it so
the dashboard can grey the card out instead of failing jobs:

```python
def available(self) -> tuple[bool, str | None]:
    # e.g. check a binary exists or a backing service responds
    return True, None          # or: return False, "Ollama is not reachable"
```

`ffmpeg` is installed by [the native installer](../deploy/install.sh) along with
Ghostscript, Tesseract, qpdf, Pandoc, and ExifTool. Add new required Ubuntu
packages to the installer's package list and Python dependencies to
[`server/requirements.txt`](../server/requirements.txt).

## 3. Test it

From your checkout on an Ubuntu or WSL2 test host, deploy the edited adapter
with the [native installer](SELF_HOSTING.md#ubuntu-2404). Wait for any existing
jobs to finish before reinstalling.

```bash
sudo bash deploy/install.sh
```

Install `jq` with `sudo apt install jq` if you want to run the shell examples.

1. Open **Tools** and check that the new tool appears. You can also query the
   catalog from a shell using your configured port and a test admin account.

   ```bash
   BASE_URL=http://127.0.0.1:8800
   TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"<your password>"}' | jq -r .access_token)
   curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/v1/tools" \
     | jq '.[] | select(.slug=="video-thumbnail")'
   ```

2. Open the tool, drop in a file, and run it. To exercise the same path through
   the API, use a sample clip in your current directory.

   ```bash
   FILE_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
     -F "file=@sample.mp4" "$BASE_URL/api/v1/files" | jq -r .id)
   JOB_ID=$(curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d "{\"tool\":\"video-thumbnail\",\"file_ids\":[\"$FILE_ID\"],\"params\":{\"timestamp\":3}}" \
     "$BASE_URL/api/v1/jobs" | jq -r .id)
   curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/v1/jobs/$JOB_ID" | jq .
   ```

   When `status` is `done`, download the output file listed under `output_files`
   via `GET /api/v1/files/{id}/download`.

3. Check worker logs with
   `sudo journalctl -u selfx-worker@default -u selfx-worker@heavy -f`.

## 4. Checklist

- [ ] One file in `server/app/tools/`, class has `@register`
- [ ] Unique `slug`; sensible `category`, `accepts`, `queue`
- [ ] All user input flows through `params_schema` (enums/numbers/booleans — no free-form strings into argv)
- [ ] Outputs written to `ctx.output_dir`, temp files to `ctx.workdir`
- [ ] `ctx.progress()` called at least at start/end for long jobs
- [ ] Failures raise `ToolError` with a user-safe message
