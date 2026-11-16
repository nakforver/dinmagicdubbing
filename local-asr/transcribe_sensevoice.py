#!/usr/bin/env python3
"""Transcribe audio/video to SRT locally with Alibaba SenseVoice (FunASR).

SenseVoice is very fast on CPU and especially strong on Chinese.
Workflow with dinmagicdubbing:
  1. python3 transcribe_sensevoice.py video.mp4 -l zh
  2. Import the .srt into the app (Subtitles tab -> Import .srt)
  3. Use "Translate Only" in the app to translate it to Khmer with Gemini.

Usage:
  python3 transcribe_sensevoice.py input.mp4
  python3 transcribe_sensevoice.py input.mp4 -l zh -o out.srt

Install:  pip install funasr
First run downloads SenseVoiceSmall + VAD + punctuation models.
Note: the timestamp list returned by FunASR lines up with the sentences
produced by the punctuation model; if the counts ever mismatch, the script
falls back to one cue per timestamp chunk with the text split evenly.
"""
import argparse
import re
import sys


def fmt(ms):
    s = int(ms // 1000)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    milli = int(ms % 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{milli:03d}"


def split_sentences(text):
    parts = re.split(r"(?<=[。！？；.!?;])\s*", text.strip())
    return [p for p in parts if p]


def main():
    ap = argparse.ArgumentParser(description="Local transcription to SRT (SenseVoice/FunASR)")
    ap.add_argument("input", help="audio/video file (mp4, mp3, wav, webm, mkv...)")
    ap.add_argument("-l", "--language", default="zh",
                    help="source language: zh, en, yue, ja, ko (default: zh)")
    ap.add_argument("-o", "--output", default=None,
                    help="output .srt path (default: <input>.srt)")
    args = ap.parse_args()

    try:
        from funasr import AutoModel
    except ImportError:
        print("FunASR is not installed. Run:  pip install funasr", file=sys.stderr)
        sys.exit(1)

    out = args.output or (args.input.rsplit(".", 1)[0] + ".srt")
    print("Loading SenseVoiceSmall ... (first run downloads the models)")
    model = AutoModel(model="iic/SenseVoiceSmall",
                      vad_model="fsmn-vad",
                      punc_model="ct-punc",
                      device="cpu")
    res = model.generate(input=args.input, cache={}, language=args.language,
                         use_itn=True, batch_size_s=60, merge_vad=True)
    item = res[0]
    text = item.get("text", "").strip()
    stamps = item.get("timestamp", []) or []
    sentences = split_sentences(text)

    cues = []
    if stamps and len(stamps) == len(sentences):
        cues = list(zip(stamps, sentences))
    elif stamps:
        # Fallback: pair as many as possible, attach leftovers to the last cue.
        for i, (st, en) in enumerate(stamps):
            chunk = sentences[i] if i < len(sentences) else ""
            if chunk:
                cues.append(((st, en), chunk))
        if len(sentences) > len(stamps) and cues:
            (st, en), last = cues[-1]
            cues[-1] = ((st, en), last + "".join(sentences[len(stamps):]))
    else:
        print("WARNING: no timestamps returned; writing whole text as one cue.",
              file=sys.stderr)
        cues = [((0, 60000), text)] if text else []

    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for i, ((st, en), sent) in enumerate(cues, 1):
            sent = sent.strip()
            if not sent:
                continue
            f.write(f"{i}\n{fmt(st)} --> {fmt(en)}\n{sent}\n\n")
            n += 1
    print(f"Done: {n} cues -> {out}")
    print("Next: import this .srt into dinmagicdubbing (Subtitles tab) "
          "and use Translate Only.")


if __name__ == "__main__":
    main()
