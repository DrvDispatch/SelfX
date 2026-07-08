#!/usr/bin/env python3
"""WhisperX runner — executed by the ISOLATED whisperx venv (its own torch), never
imported by the main app. Transcribe -> word-align -> (optional) diarize, then emit
a normalized JSON the transcribe tool reads back.

Usage (called via subprocess from server/app/tools/transcribe.py):
  python _whisperx_run.py --audio in.wav --model large-v3 --language auto \
      --out result.json [--diarize --hf-token HF_xxx] [--batch-size 16]

Leading underscore keeps the tool auto-discovery from importing it in the main venv.
"""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="auto")
    ap.add_argument("--task", default="transcribe")
    ap.add_argument("--out", required=True)
    ap.add_argument("--diarize", action="store_true")
    ap.add_argument("--hf-token", default="")
    ap.add_argument("--batch-size", type=int, default=16)
    args = ap.parse_args()
    # Token: prefer the inherited env (the worker sources selfx.env) over argv so it
    # never shows up in `ps`; fall back to --hf-token for standalone use.
    import os
    hf_token = os.environ.get("HUGGINGFACE_TOKEN", "") or args.hf_token

    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    language = None if args.language.strip().lower() in ("", "auto") else args.language.strip().lower()

    asr_opts = {}
    model = whisperx.load_model(
        args.model, device, compute_type=compute_type, language=language,
        task=args.task, asr_options=asr_opts or None,
    )
    audio = whisperx.load_audio(args.audio)
    result = model.transcribe(audio, batch_size=max(1, args.batch_size), language=language)
    lang = result.get("language") or language or "en"

    # word-level alignment (WhisperX's headline feature)
    aligned = result
    try:
        align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
        aligned = whisperx.align(
            result["segments"], align_model, meta, audio, device,
            return_char_alignments=False,
        )
    except Exception as exc:  # some languages lack an alignment model — keep segment timing
        print(f"align skipped: {exc}", file=sys.stderr)

    # optional speaker diarization (needs a HuggingFace token for pyannote)
    if args.diarize and hf_token:
        try:
            try:
                from whisperx.diarize import DiarizationPipeline, assign_word_speakers
            except Exception:
                from whisperx import DiarizationPipeline, assign_word_speakers
            try:
                diarize = DiarizationPipeline(token=hf_token, device=device)
            except TypeError:
                # older WhisperX used use_auth_token=
                diarize = DiarizationPipeline(use_auth_token=hf_token, device=device)
            diarize_segments = diarize(audio)
            n_turns = len(diarize_segments) if diarize_segments is not None else 0
            aligned = assign_word_speakers(diarize_segments, aligned, fill_nearest=True)
            n_labeled = sum(1 for s in aligned.get("segments", []) if s.get("speaker"))
            print(f"diarization: {n_turns} turns, {n_labeled} segments labeled", file=sys.stderr)
        except Exception as exc:
            import traceback
            print(f"diarization skipped: {exc}\n{traceback.format_exc()}", file=sys.stderr)

    out_segments = []
    for s in aligned.get("segments", []):
        seg = {
            "start": s.get("start"),
            "end": s.get("end"),
            "text": (s.get("text") or "").strip(),
        }
        if s.get("speaker"):
            seg["speaker"] = s["speaker"]
        words = s.get("words")
        if words:
            seg["words"] = [
                {"start": w.get("start"), "end": w.get("end"),
                 "word": w.get("word"), "speaker": w.get("speaker")}
                for w in words
            ]
        out_segments.append(seg)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"language": lang, "segments": out_segments}, fh, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
