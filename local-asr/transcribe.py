#!/usr/bin/env python3
"""Transcribe audio/video to SRT locally with faster-whisper (no API key, no cloud).

Workflow with dinmagicdubbing:
  1. python3 transcribe.py video.mp4 -l zh
  2. Import the .srt into the app (Subtitles tab -> Import .srt)
  3. Use "Translate Only" in the app to translate it to Khmer with Gemini.

Usage:
  python3 transcribe.py input.mp4
  python3 transcribe.py input.mp4 -m medium -l zh -o out.srt

Models (bigger = more accurate, slower): tiny, base, small, medium, large-v3.
For Chinese drama dialogue, large-v3 is best; medium is a good CPU compromise.
First run downloads the model from Hugging Face (~1-3 GB for large-v3).

Requirements: Python 3.9+, ffmpeg in PATH, faster-whisper (pip install faster-whisper).
Audio is decoded with ffmpeg (not PyAV), so it works regardless of the
installed PyAV version.
"""
import argparse
import subprocess
import sys

import numpy as np


def fmt(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_audio_16k(path):
    """Decode any audio/video file to mono 16 kHz float32 samples via ffmpeg."""
    cmd = ["ffmpeg", "-v", "error", "-i", path,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    try:
        raw = subprocess.check_output(cmd)
    except FileNotFoundError:
        print("ffmpeg is not installed or not in PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        print(f"ffmpeg could not read: {path}", file=sys.stderr)
        sys.exit(1)
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size == 0:
        print(f"No audio found in: {path}", file=sys.stderr)
        sys.exit(1)
    return audio


def main():
    ap = argparse.ArgumentParser(description="Local transcription to SRT (faster-whisper)")
    ap.add_argument("input", help="audio/video file (mp4, mp3, wav, webm, mkv...)")
    ap.add_argument("-m", "--model", default="large-v3",
                    help="whisper model: tiny/base/small/medium/large-v3 (default: large-v3)")
    ap.add_argument("-l", "--language", default="zh",
                    help="source language code, e.g. zh, en, ko, ja (default: zh)")
    ap.add_argument("-o", "--output", default=None,
                    help="output .srt path (default: <input>.srt)")
    args = ap.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed. Run:  pip install faster-whisper",
              file=sys.stderr)
        sys.exit(1)

    out = args.output or (args.input.rsplit(".", 1)[0] + ".srt")
    print(f"Loading model '{args.model}' ... (first run downloads it)")
    model = WhisperModel(args.model, device="auto", compute_type="auto")
    print("Decoding audio with ffmpeg ...")
    audio = load_audio_16k(args.input)
    segments, info = model.transcribe(audio, language=args.language,
                                      vad_filter=True)
    print(f"Detected language: {info.language} "
          f"(probability {info.language_probability:.2f})")

    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            text = seg.text.strip()
            if not text:
                continue
            f.write(f"{i}\n{fmt(seg.start)} --> {fmt(seg.end)}\n{text}\n\n")
            n += 1
    print(f"Done: {n} cues -> {out}")
    print("Next: import this .srt into dinmagicdubbing (Subtitles tab) "
          "and use Translate Only.")


if __name__ == "__main__":
    main()
