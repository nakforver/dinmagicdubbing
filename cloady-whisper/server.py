#!/usr/bin/env python3
"""Transcription server for dinmagicdubbing, hosted on Cloady (free tier).

This is the Cloady twin of whisper-server.py: the same HTTP contract,
but it runs in the cloud so the app on the phone can reach it too.

    GET  /healthz     -> {"ok": true, "service": "dinmagic-whisper",
                          "model": "tiny", "engines": ["whisper"]}
    POST /transcribe  -> body: raw media bytes (the video/audio file itself)
                         headers: X-Filename (original name, optional),
                                  X-Language (e.g. zh, en, ko; empty = auto),
                                  X-Engine (only "whisper" on this server)
                         -> {"srt": "...", "language": "zh", "cues": 42}

Why Whisper tiny?
  The free tier gives this app 0.25 CPU / 0.5 GB RAM. Measured on CPU:
    faster-whisper tiny (int8):  ~325 MB peak RSS, ~3.7x realtime on 1 core
    faster-whisper base (int8):  ~482 MB peak RSS — 94% of the 512 MB limit,
                                 a 9-minute clip would push it over -> OOM.
    SenseVoiceSmall (FunASR + torch): ~2 GB for one stream — does not fit.
    Qwen3-ASR 0.6B (transformers + torch): ~1.2 GB+ — does not fit.
  Tiny is the only local model that genuinely fits. On clear Chinese it
  transcribes the words but makes homophone errors (e.g. 世界→事件 on
  the test clip); on fast natural drama dialogue it is weaker than the
  medium model — for the most accurate transcript, still run
  whisper-server.py (medium) on your computer.
  MEASURED on Cloady JPN1 (0.25 CPU, cpu_threads=1): first transcribe
  of 35 s audio took 3m15s (model load ~2 min + inference ~1 min);
  warm transcribe ~2x realtime + ~15 s overhead (3 s clip took 22 s).
  A 9-minute video takes ~18 min warm — a single request may time out
  on long videos. EU1 is UNUSABLE (host CPU starvation: model load
  5-10+ min, ~7x realtime) — use JPN1.

Notes:
  - ffmpeg comes from the imageio-ffmpeg package (static binary), so the
    image needs no apt packages. Audio is decoded with ffmpeg (not PyAV),
    so it works regardless of the installed PyAV version.
  - `cpu_threads=1`: the container has only 0.25 CPU and the host node
    is contended — letting ctranslate2 spawn one thread per host core
    thrashes under such a small CPU quota. A single inference thread
    is far faster here than the default (all host cores).
  - The model downloads from HuggingFace Hub on FIRST USE (~75 MB) and
    is cached in the container; the first transcribe takes a minute more.
    On Cloady the model is BAKED INTO THE IMAGE at build time instead
    (railpack.json build step downloads it to /app/hf-cache), because
    the runtime container's download from HuggingFace Hub stalls — so
    the first transcribe is fast and needs no HF access at runtime.
    server.py prefers /app/hf-cache when that directory exists.
  - The model is chosen with WHISPER_MODEL (default "tiny") or --model.
    Do not set it to small/medium/large on this tier — the container
    will run out of memory.
  - Listens on 0.0.0.0:$PORT (default 8000). No API keys are needed or
    used here: transcription is 100% local and free.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "tiny")
_model = None


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fmt(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ffmpeg_exe():
    """System ffmpeg if present, else the static binary from imageio-ffmpeg."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def load_audio_16k(path):
    """Decode any audio/video file to mono 16 kHz float32 samples via ffmpeg."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.check_output(cmd)
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size == 0:
        raise ValueError("no audio found in the uploaded file")
    return audio


def get_model():
    global _model
    if _model is None:
        # Prefer the model baked into the image at build time
        # (railpack.json build step downloads it to /app/hf-cache).
        # Only when that directory exists; otherwise the default
        # HuggingFace cache is used. Must be set BEFORE importing
        # faster_whisper, which reads HF_HOME at import time.
        baked = os.path.isdir("/app/hf-cache")
        if baked:
            os.environ.setdefault("HF_HOME", "/app/hf-cache")
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper មិនទាន់ដំឡើងទេ — run: pip install faster-whisper")
        log(f"Loading Whisper model '{WHISPER_MODEL}' ... " +
            ("(baked into the image)" if baked else
             "(first run downloads it from HuggingFace Hub)"))
        _model = WhisperModel(WHISPER_MODEL, device="cpu",
                              compute_type="int8", cpu_threads=1)
        log("Whisper model ready.")
    return _model


def transcribe_file(path, language):
    model = get_model()
    audio = load_audio_16k(path)
    lang = language or None  # None = auto-detect
    segments, info = model.transcribe(audio, language=lang, vad_filter=True)
    lines = []
    n = 0
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"{i}\n{fmt(seg.start)} --> {fmt(seg.end)}\n{text}\n")
        n += 1
    return "\n".join(lines), info.language, n


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the console tidy
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Filename, X-Language, X-Engine")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/healthz"):
            self._json(200, {"ok": True, "service": "dinmagic-whisper",
                             "model": WHISPER_MODEL,
                             "engines": ["whisper"]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/transcribe":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"error": "empty upload"})
            return
        engine = (self.headers.get("X-Engine") or "whisper").strip().lower()
        if engine != "whisper":
            self._json(400, {"error": f"engine '{engine}' is not on this "
                                      "server (Whisper tiny only) — run "
                                      "whisper-server.py on your computer "
                                      "for SenseVoice / Qwen3-ASR"})
            return
        data = self.rfile.read(length)
        filename = self.headers.get("X-Filename") or "upload.mp4"
        language = (self.headers.get("X-Language") or "zh").strip()
        suffix = os.path.splitext(filename)[1] or ".mp4"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.close()
            log(f"Transcribing {filename} ({length / 1e6:.1f} MB, "
                f"lang={language or 'auto'}, model={WHISPER_MODEL}) ...")
            srt, detected, n = transcribe_file(tmp.name, language)
            log(f"Done: {n} cues, language={detected}")
            self._json(200, {"srt": srt, "language": detected, "cues": n})
        except Exception as exc:  # noqa: BLE001 - report any failure to the app
            log(f"ERROR: {exc}")
            self._json(500, {"error": str(exc)})
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


def main():
    global WHISPER_MODEL
    ap = argparse.ArgumentParser(
        description="Cloud transcription server for dinmagicdubbing "
                    "(Whisper tiny, Cloady free tier)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--model", default=WHISPER_MODEL,
                    help="whisper model (default: tiny — the only one "
                         "that fits 0.5 GB RAM)")
    args = ap.parse_args()
    WHISPER_MODEL = args.model
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"dinmagic-whisper listening on http://{args.host}:{args.port} "
        f"(model={WHISPER_MODEL})")
    log("Model loads on first transcribe (downloads ~75 MB on first use).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Stopping.")
        server.shutdown()


if __name__ == "__main__":
    main()
