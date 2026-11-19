# Tool catalog

SelfX includes **63 file tools**. Find them under **Tools** by name or category. The tool ID in backticks is what the API and saved tool presets use.

Some tools need additional engines or services. The catalog notes dependencies outside the standard [Ubuntu and WSL2 installation](SELF_HOSTING.md). Model-based tools can download weights the first time you use them.

## PDF

| Tool | What it does |
| --- | --- |
| Compress PDF (`pdf-compress`) | Shrink a PDF by downsampling and re-encoding its images. |
| Extract text from PDF (`pdf-extract-text`) | Save a PDF's text layer as plain text. Use OCR first for image-only pages. |
| Merge PDFs (`pdf-merge`) | Combine multiple PDFs into one document in upload order. |
| Organize PDF pages (`pdf-organize`) | Preview, reorder, or remove pages and save the result as a new PDF. |
| Password-protect PDF (`pdf-protect`) | Encrypt a PDF with a password using AES-256 or AES-128. |
| PDF to images (`pdf-to-images`) | Render pages as PNG, JPEG, or WebP. Multiple page images are bundled in a ZIP. |
| PDF to Word (`pdf-to-docx`) | Convert a PDF to an editable DOCX and reconstruct its layout. |
| Rotate PDF (`pdf-rotate`) | Rotate all or selected pages by 90, 180, or 270 degrees. |
| Split PDF (`pdf-split`) | Extract a page range or split each page into its own PDF. |
| Unlock PDF (`pdf-unlock`) | Remove the protection from a PDF using its current password. |
| Watermark PDF (`pdf-watermark`) | Stamp text on selected pages with adjustable angle and opacity. |

## Documents

| Tool | What it does |
| --- | --- |
| Convert ebook (`ebook-convert`) | Convert between supported ebook and document formats such as EPUB, MOBI, DOCX, and TXT. Requires Calibre. |
| HTML to PDF (`html-to-pdf`) | Render an HTML file as PDF with CSS page layout. Requires WeasyPrint. |
| Image to text (OCR) (`image-to-text`) | Extract printed text from a photo, screenshot, or scan. |
| Markup convert (`pandoc-convert`) | Convert supported text and document formats such as Markdown, HTML, DOCX, and EPUB. PDF output requires WeasyPrint. |
| OCR (searchable PDF) (`ocr-pdf`) | Add a searchable text layer to scanned PDF pages. |
| Office / HTML / Markdown to PDF (`office-convert`) | Convert Office documents, HTML, Markdown, and plain text to PDF. |
| PDF to Markdown (`pdf-to-markdown`) | Convert PDF, DOCX, or PPTX files to structured Markdown. Requires Docling. |

## Images

| Tool | What it does |
| --- | --- |
| Describe image (AI) (`image-caption`) | Generate a caption for an image using an Ollama vision model. |
| Image convert / resize (`image-convert`) | Convert an image to a different format, resize it, or strip metadata. |
| Image to icon (.ico) (`image-to-ico`) | Export a multi-size Windows icon or favicon. |
| Images to PDF (`images-to-pdf`) | Combine images into one PDF with one image per page. |
| Optimize image (`image-optimize`) | Reduce image file size, with an optional size limit for JPEG and WebP. |
| Remove background (`image-remove-bg`) | Remove a photo's background and export a transparent PNG. Requires rembg. |
| Upscale image (AI) (`image-upscale`) | Enlarge an image 4× with an upscaling model. Requires spandrel and a CUDA-enabled PyTorch runtime. |

## Video and audio

| Tool | What it does |
| --- | --- |
| Audio / Video convert (`media-convert`) | Convert media to formats such as MP4, WebM, MP3, WAV, FLAC, and Opus. |
| Burn in subtitles (`video-burn-subtitles`) | Embed captions permanently in the video image using an SRT, WebVTT, or ASS file. |
| Change video speed (`video-speed`) | Play a video faster or slower while preserving audio pitch. |
| Compress video to a size limit (`video-target-size`) | Produce an MP4 to fit an upload limit, with optional audio. |
| Crop video (`video-crop`) | Crop to a preset aspect ratio or a custom rectangle. |
| Download from URL (`media-download`) | Download video or audio from a supported media URL. Requires yt-dlp and internet access. |
| Extract audio (`audio-extract`) | Save an audio track as MP3, AAC, M4A, WAV, FLAC, or Opus. |
| Fade in / out (`video-fade`) | Add fades at the start or end of a clip. |
| Isolate vocals / instrumental (`voice-isolation`) | Separate a track into vocals and instruments. Requires audio-separator and a model. |
| Join videos (`video-concat`) | Combine clips in the order you upload them. |
| Mute video (`video-mute`) | Remove a video's audio track without re-encoding the picture. |
| Normalize audio (`audio-normalize`) | Adjust perceived audio loudness for more consistent playback. |
| Remove background noise (`speech-denoise`) | Reduce steady background noise such as fan hum or hiss. |
| Remove silence (auto-cut) (`video-remove-silence`) | Cut quiet sections out of a video. |
| Resize video (`video-resize`) | Scale a video to a standard resolution while preserving its aspect ratio. |
| Reverse video (`video-reverse`) | Reverse the video and its audio. Best suited to short clips. |
| Rotate / flip video (`video-rotate`) | Rotate or mirror a video. |
| Trim video (`video-trim`) | Cut a clip from a longer video by time. |
| Video thumbnail (`video-thumbnail`) | Save a frame at a chosen time as JPEG, PNG, or WebP. |
| Video to GIF (`gif-from-video`) | Turn a section of a video into an animated GIF or WebP. |
| Watermark video (`video-watermark`) | Overlay a logo or other image on a video. |

## Subtitles

| Tool | What it does |
| --- | --- |
| Clean subtitle cues (`subtitle-cleanup`) | Sort and renumber SRT or WebVTT cues, remove duplicates, or shift timestamps. |
| Convert subtitles (`subtitle-convert`) | Change subtitle format between SRT, WebVTT, and ASS. |
| Export edited transcript (`transcript-export`) | Turn an edited SelfX transcript JSON file into a timestamped PDF and SRT captions. |
| Extract subtitles (`subtitle-extract`) | Save an embedded subtitle track from a video as an SRT file. |
| Sync subtitles (`subtitle-sync`) | Shift and stretch subtitle timing to match a recording. Requires ffsubsync. |

## AI and transcription

| Tool | What it does |
| --- | --- |
| AI Summarize (`ai-summarize`) | Summarize a PDF, Word, TXT, or Markdown document with an Ollama text model. |
| Ask a document (`doc-qa`) | Ask an Ollama text model questions about an uploaded document. |
| Chat with documents (RAG) (`multi-doc-qa`) | Retrieve relevant passages across documents and answer a question. Requires Ollama text and embedding models. |
| Summarize audio (notes) (`audio-summary`) | Transcribe a recording and produce notes or action items using Whisper and an Ollama text model. |
| Transcribe audio / video (`transcribe`) | Run local Whisper and export TXT, SRT, WebVTT, or timed JSON. |

## Utilities

| Tool | What it does |
| --- | --- |
| Barcode (`barcode-generate`) | Create a 1D barcode such as Code 128, EAN-13, or UPC-A. Requires python-barcode. |
| Compress files (`archive-compress`) | Bundle files into a ZIP, 7z, tar.gz, or tar.xz archive. |
| Extract archive (`archive-extract`) | Extract files from a supported ZIP, 7z, tar, or compressed archive. |
| File checksum (`hash-checksum`) | Generate checksums with algorithms including SHA-256, BLAKE2, and CRC32. |
| QR code (`qr-generate`) | Turn text or a URL into a PNG or SVG QR code. |
| Remove metadata (`metadata-remove`) | Strip metadata from supported image, PDF, or Office files. |
| Virus scan (`virus-scan`) | Scan files and report the verdict. Requires a reachable ClamAV daemon. |
