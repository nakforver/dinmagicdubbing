#!/usr/bin/env python3
"""Local Whisper transcription server for dinmagicdubbing.

Run this on your computer (where the video files are):

    pip install faster-whisper
    python3 whisper-server.py [--host 127.0.0.1] [--port 8001] [--model medium]

Then open the dinmagicdubbing app, go to the Subtitles tab and press
"Transcribe with Whisper". The app sends the loaded video to this server,
and the server fills the subtitle box with the transcript (.srt).
After that, choose Translate Only in the app and Gemini translates it
to Khmer. No audio is ever sent to Gemini, so Gemini quota is saved.

Endpoints:
  GET  /healthz     -> {"ok": true, "service": "whisper-transcribe", "model": ...}
  POST /transcribe  -> body: raw media bytes (the video/audio file itself)
                       headers: X-Filename (original name, optional),
                                X-Language (e.g. zh, en, ko; empty = auto)
                       -> {"srt": "...", "language": "zh", "cues": 42}

Notes:
  - Requires: faster-whisper (pip install faster-whisper) and ffmpeg in PATH.
  - The server only listens on localhost by default, so only your own
    computer can reach it. Use --host 0.0.0.0 only on a trusted network.
  - Audio is decoded with ffmpeg (not PyAV), so it works regardless of
    the installed PyAV version.
  - Transcription runs on CPU; a 9-minute video takes roughly 10-20
    minutes with the medium model. The model loads once at startup.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

MODEL = "medium"
_engine = None


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


def load_audio_16k(path):
    """Decode any audio/video file to mono 16 kHz float32 samples via ffmpeg."""
    cmd = ["ffmpeg", "-v", "error", "-i", path,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.check_output(cmd)
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size == 0:
        raise ValueError("no audio found in the uploaded file")
    return audio


def get_engine():
    global _engine
    if _engine is None:
        from faster_whisper import WhisperModel
        log(f"Loading Whisper model '{MODEL}' ...")
        _engine = WhisperModel(MODEL, device="auto", compute_type="auto")
        log("Model ready.")
    return _engine


def transcribe_file(path, language):
    model = get_engine()
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
                         "Content-Type, X-Filename, X-Language")

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
            self._json(200, {"ok": True, "service": "whisper-transcribe",
                             "model": MODEL})
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
        data = self.rfile.read(length)
        filename = self.headers.get("X-Filename") or "upload.mp4"
        language = (self.headers.get("X-Language") or "zh").strip()
        suffix = os.path.splitext(filename)[1] or ".mp4"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.close()
            log(f"Transcribing {filename} ({length / 1e6:.1f} MB, lang={language or 'auto'}) ...")
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
    global MODEL
    ap = argparse.ArgumentParser(description="Local Whisper server for dinmagicdubbing")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--model", default="medium",
                    help="whisper model: tiny/base/small/medium/large-v3")
    args = ap.parse_args()
    MODEL = args.model
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("faster-whisper is not installed. Run:  pip install faster-whisper",
              file=sys.stderr)
        sys.exit(1)
    get_engine()  # load the model before serving, so first request is fast
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"Whisper server listening on http://{args.host}:{args.port} (model={MODEL})")
    log("In the app: Subtitles tab -> Transcribe with Whisper.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Stopping.")
        server.shutdown()


if __name__ == "__main__":
    main()
