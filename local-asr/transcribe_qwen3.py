#!/usr/bin/env python3
"""Transcribe audio/video to SRT locally with Qwen3-ASR (transformers).

Qwen3-ASR is Alibaba's newest ASR model (2025): very accurate Chinese,
52 languages. The ASR model itself returns no timestamps, so this script
transcribes in 30-second chunks and spreads each chunk's sentences over
its time window to build the .srt. (Word-level timestamps need the
separate Qwen3-ForcedAligner model — not used here.)

Workflow with dinmagicdubbing:
  1. python3 transcribe_qwen3.py video.mp4 -l zh
  2. Import the .srt into the app (Subtitles tab -> Import .srt)
  3. Use "Translate Only" in the app to translate it to Khmer with Gemini.

Or run whisper-server.py and pick Qwen3-ASR in the app's Subtitles tab.

Usage:
  python3 transcribe_qwen3.py input.mp4
  python3 transcribe_qwen3.py input.mp4 -l zh -o out.srt
  python3 transcribe_qwen3.py input.mp4 --model Qwen/Qwen3-ASR-1.7B-hf

Install:  pip install "transformers>=5.13.0" torch
First run downloads the model from Hugging Face (~1.2 GB for 0.6B).
Runs on CPU (float32); a GPU is faster but not required.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import os

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


def write_wav_16k(path, audio):
    """Write mono 16 kHz float32 samples to a 16-bit PCM WAV file."""
    import wave
    pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    data = (pcm * 32767).astype(np.int16).tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(data)


def split_sentences(text):
    parts = re.split(r"(?<=[。！？；.!?;])\s*", (text or "").strip())
    return [p for p in parts if p]


def split_long_sentence(text, max_chars=30):
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def cues_from_text(text, start_s, end_s):
    """Spread a chunk's text over its time window, proportionally to
    sentence length."""
    sentences = split_sentences(text)
    if not sentences:
        return []
    duration = max(end_s - start_s, 0.1)
    total = sum(len(s) for s in sentences) or 1
    cues = []
    t = start_s
    for sent in sentences:
        span = duration * len(sent) / total
        for piece in split_long_sentence(sent):
            piece_span = span * len(piece) / max(len(sent), 1)
            cues.append((t, t + piece_span, piece))
            t += piece_span
    return cues


LANG_NAMES = {
    "Chinese": "zh", "English": "en", "Cantonese": "yue",
    "Korean": "ko", "Japanese": "ja", "Arabic": "ar", "German": "de",
    "French": "fr", "Spanish": "es", "Portuguese": "pt",
    "Indonesian": "id", "Italian": "it", "Russian": "ru", "Thai": "th",
    "Vietnamese": "vi", "Turkish": "tr", "Hindi": "hi", "Malay": "ms",
    "Dutch": "nl", "Swedish": "sv", "Danish": "da", "Finnish": "fi",
    "Polish": "pl", "Czech": "cs", "Filipino": "fil", "Persian": "fa",
    "Greek": "el", "Hungarian": "hu", "Macedonian": "mk",
    "Romanian": "ro",
}


def main():
    ap = argparse.ArgumentParser(
        description="Local transcription to SRT (Qwen3-ASR / transformers)")
    ap.add_argument("input", help="audio/video file (mp4, mp3, wav, webm, mkv...)")
    ap.add_argument("-l", "--language", default="zh",
                    help="source language code, e.g. zh, en, ko, ja (default: zh)")
    ap.add_argument("-o", "--output", default=None,
                    help="output .srt path (default: <input>.srt)")
    ap.add_argument("--model", default="Qwen/Qwen3-ASR-0.6B-hf",
                    help="Qwen3-ASR model id (default: Qwen/Qwen3-ASR-0.6B-hf; "
                         "1.7B: Qwen/Qwen3-ASR-1.7B-hf)")
    ap.add_argument("--chunk", type=int, default=30,
                    help="seconds of audio per generate call (default: 30)")
    args = ap.parse_args()

    try:
        import torch
        from transformers import (AutoModelForMultimodalLM, AutoProcessor)
    except ImportError:
        print('transformers/torch are not installed. Run:\n'
              '  pip install "transformers>=5.13.0" torch', file=sys.stderr)
        sys.exit(1)

    out = args.output or (args.input.rsplit(".", 1)[0] + ".srt")
    print(f"Loading model '{args.model}' ... (first run downloads ~1.2 GB)")
    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model, dtype=torch.float32, device_map="auto")
    print("Decoding audio with ffmpeg ...")
    audio = load_audio_16k(args.input)
    duration = len(audio) / 16000.0
    lang = args.language or None  # None = auto-detect
    detected = lang or "zh"

    cues = []
    n_chunks = max(1, int((duration + args.chunk - 1) // args.chunk))
    for ci in range(n_chunks):
        start = ci * args.chunk
        end = min(duration, start + args.chunk)
        seg = audio[int(start * 16000):int(end * 16000)]
        if seg.size == 0:
            continue
        print(f"Transcribing {start:.0f}s-{end:.0f}s "
              f"(chunk {ci + 1}/{n_chunks}) ...")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        try:
            tmp.close()
            write_wav_16k(tmp.name, seg)
            kwargs = {"audio": tmp.name}
            if lang:
                kwargs["language"] = lang
            inputs = processor.apply_transcription_request(**kwargs)
            inputs = inputs.to(model.device, model.dtype)
            with torch.inference_mode():
                output_ids = model.generate(**inputs, max_new_tokens=1024)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        parsed = processor.decode(generated_ids,
                                  return_format="parsed")[0]
        text = (parsed.get("transcription") or "").strip()
        if parsed.get("language"):
            detected = LANG_NAMES.get(parsed["language"],
                                      parsed["language"])
        if not text:
            continue
        cues.extend(cues_from_text(text, start, end))

    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for i, (st, en, text) in enumerate(cues, 1):
            text = text.strip()
            if not text:
                continue
            f.write(f"{i}\n{fmt(st)} --> {fmt(en)}\n{text}\n\n")
            n += 1
    print(f"Detected language: {detected}")
    print(f"Done: {n} cues -> {out}")
    print("Next: import this .srt into dinmagicdubbing (Subtitles tab) "
          "and use Translate Only.")


if __name__ == "__main__":
    main()
