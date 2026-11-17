#!/usr/bin/env python3
"""Transcription server for dinmagicdubbing, hosted on Cloady (free tier).

This is the Cloady twin of whisper-server.py: the same HTTP contract,
but it runs in the cloud so the app on the phone can reach it too.

    GET  /healthz     -> {"ok": true, "service": "dinmagic-whisper",
                          "model": "tiny", "engines": ["whisper"],
                          "max_minutes": 60}
    POST /transcribe  -> body: raw media bytes (the video/audio file itself)
                         headers: X-Filename (original name, optional),
                                  X-Language (e.g. zh, en, ko; empty = auto),
                                  X-Engine (only "whisper" on this server)
                         -> 202 {"job": "<id>", "status": "queued"}
                         (the upload is saved and transcribed in the
                         background — poll GET /job/<id> instead of
                         waiting on one long request)
    GET  /job/<id>    -> {"status": "queued|loading|processing|done|error",
                          "progress": 0-100, "srt": "...", "cues": 42,
                          "language": "zh", "error": ""}
                         Jobs are kept for 2 hours, then deleted.

Why async jobs?
  A large video upload plus transcription takes far longer than any
  browser/proxy request timeout (a 9-minute video is ~18 min warm on
  this tier). The old single-request POST froze the app's button for
  the whole time. Now the upload returns immediately with a job id
  and the app polls for progress.

Why chunked transcription?
  The free tier gives this app 0.25 CPU / 0.5 GB RAM. Decoding a whole
  long file into one numpy array would OOM (2 h of 16 kHz float32 is
  ~460 MB). Audio is decoded and transcribed in ~10-minute chunks
  (TRANSCRIBE_CHUNK_S, default 600 s) and the SRT cues are merged
  with offset timestamps. Maximum audio length is 60 minutes
  (MAX_AUDIO_MINUTES) — longer uploads are refused with a clear
  error naming the limit instead of crashing the server.

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
  A 9-minute video takes ~18 min warm. EU1 is UNUSABLE (host CPU
  starvation: model load 5-10+ min, ~7x realtime) — use JPN1.

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
  - Only ONE job runs at a time (a FIFO queue + single worker thread):
    with 0.25 CPU, parallel transcriptions would only slow each other
    down. Extra uploads wait in "queued" status.
  - Listens on 0.0.0.0:$PORT (default 8000). No API keys are needed or
    used here: transcription is 100% local and free.
"""
import argparse
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "tiny")
# Audio is transcribed in chunks of this many seconds (default 10 min);
# override for tests (e.g. TRANSCRIBE_CHUNK_S=30). One chunk of mono
# 16 kHz float32 is ~38 MB at 600 s — safe inside 0.5 GB RAM.
CHUNK_S = int(os.environ.get("TRANSCRIBE_CHUNK_S", "600"))
MAX_AUDIO_MINUTES = 60
MAX_AUDIO_S = MAX_AUDIO_MINUTES * 60
JOB_TTL_S = 2 * 3600  # finished jobs (and their SRT) are kept 2 hours
_model = None

# ---------------------------------------------------------------- jobs

_jobs = {}  # job id -> dict(status, progress, srt, cues, language, error, ...)
_jobs_lock = threading.Lock()
_job_queue = queue.Queue()
_worker_started = False


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _unlink(path):
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _purge_old_jobs():
    """Drop finished jobs older than JOB_TTL_S (and their temp files)."""
    now = time.time()
    with _jobs_lock:
        stale = [jid for jid, j in _jobs.items()
                 if j["status"] in ("done", "error")
                 and now - j["created"] > JOB_TTL_S]
        for jid in stale:
            _unlink(_jobs.pop(jid).get("path"))


def _set_job(jid, **kw):
    with _jobs_lock:
        job = _jobs.get(jid)
        if job is not None:
            job.update(kw)


def _get_job(jid):
    with _jobs_lock:
        job = _jobs.get(jid)
        return dict(job) if job is not None else None


def _job_public(job):
    return {"status": job["status"], "progress": job["progress"],
            "srt": job["srt"], "cues": job["cues"],
            "language": job["language"], "error": job["error"]}


def _ensure_worker():
    global _worker_started
    if not _worker_started:
        threading.Thread(target=_worker, daemon=True).start()
        _worker_started = True


def _worker():
    while True:
        jid = _job_queue.get()
        try:
            _run_job(jid)
        except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
            log(f"job {jid} ERROR: {exc}")
            _set_job(jid, status="error", error=str(exc), progress=0)
        finally:
            _job_queue.task_done()


def _run_job(jid):
    job = _get_job(jid)
    if job is None:
        return
    path, language = job["path"], job["language_req"]
    try:
        _set_job(jid, status="loading", progress=5)
        srt, detected, n = transcribe_whisper_chunked(
            path, language,
            lambda frac: _set_job(
                jid, status="processing",
                progress=20 + int(75 * max(0.0, min(1.0, frac or 0.0)))))
        _set_job(jid, status="done", progress=100, srt=srt, cues=n,
                 language=detected)
        log(f"job {jid} done: {n} cues, language={detected}")
    finally:
        _unlink(path)


# ---------------------------------------------------------------- audio

def fmt(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_from_cues(cues):
    """cues: list of (start_s, end_s, text) -> (srt_text, cue_count)."""
    lines = []
    n = 0
    for i, (st, en, text) in enumerate(cues, 1):
        text = (text or "").strip()
        if not text:
            continue
        lines.append(f"{i}\n{fmt(st)} --> {fmt(en)}\n{text}\n")
        n += 1
    return "\n".join(lines), n


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


def probe_duration(path):
    """Total audio duration in seconds via `ffmpeg -i`, or None if unknown."""
    try:
        proc = subprocess.run([ffmpeg_exe(), "-i", path],
                              capture_output=True, text=True, timeout=120)
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)",
                      proc.stderr or "")
        if not m:
            return None
        return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                + float(m.group(3)))
    except Exception:
        return None


def decode_range(path, start, length):
    """Decode [start, start+length) to mono 16 kHz float32 samples.

    -ss before -i seeks fast; for audio this is accurate to a few ms,
    which is fine for SRT cue boundaries.
    """
    cmd = [ffmpeg_exe(), "-v", "error", "-ss", str(start), "-t", str(length),
           "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.check_output(cmd)
    return np.frombuffer(raw, dtype=np.float32)


def iter_audio_chunks(path, duration=None):
    """Yield (start_s, float32 mono 16 kHz samples) per CHUNK_S seconds.

    Only one chunk (~38 MB at 600 s) is ever in memory, so a 60-minute
    file never blows the 0.5 GB limit. When the duration is unknown the
    loop decodes until EOF.
    """
    if duration is None:
        duration = probe_duration(path)
    if duration is not None:
        n = max(1, int(math.ceil(duration / CHUNK_S)))
        for i in range(n):
            start = i * CHUNK_S
            length = min(CHUNK_S, duration - start)
            if length <= 0:
                break
            yield start, decode_range(path, start, length)
    else:
        start = 0.0
        while True:
            audio = decode_range(path, start, CHUNK_S)
            if audio.size == 0:
                break
            yield start, audio
            start += CHUNK_S


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


def transcribe_whisper_chunked(path, language, progress_cb=None):
    """Transcribe in CHUNK_S pieces, merging cues with offset timestamps.

    progress_cb(frac) is called after each chunk with the fraction of
    the audio processed so far (0..1, or None when the duration is
    unknown). The language detected on the first chunk is reused for
    later chunks so one clip never flips language mid-way.
    """
    model = get_model()
    duration = probe_duration(path)
    lang = language or None  # None = auto-detect
    detected = None
    cues = []
    processed = 0.0
    for start, audio in iter_audio_chunks(path, duration):
        if audio.size == 0:
            continue
        segments, info = model.transcribe(audio, language=lang or detected,
                                          vad_filter=True)
        if detected is None:
            detected = info.language
        for seg in segments:
            text = seg.text.strip()
            if text:
                cues.append((start + seg.start, start + seg.end, text))
        processed = start + len(audio) / 16000.0
        if processed > MAX_AUDIO_S:
            raise ValueError(
                f"audio លើស {MAX_AUDIO_MINUTES} នាទី — សូមកាត់វីដេអូឱ្យខ្លីជាង "
                f"{MAX_AUDIO_MINUTES} នាទី (audio over {MAX_AUDIO_MINUTES} min)")
        if progress_cb is not None:
            progress_cb(processed / duration if duration else None)
    srt, n = srt_from_cues(cues)
    if n == 0:
        raise ValueError("no speech found in the uploaded file")
    return srt, detected or language or "zh", n


# ---------------------------------------------------------------- HTTP

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
        _purge_old_jobs()
        if self.path in ("/", "/healthz"):
            self._json(200, {"ok": True, "service": "dinmagic-whisper",
                             "model": WHISPER_MODEL,
                             "engines": ["whisper"],
                             "max_minutes": MAX_AUDIO_MINUTES})
            return
        m = re.match(r"^/job/([A-Za-z0-9_-]+)$", self.path.split("?")[0])
        if m:
            job = _get_job(m.group(1))
            if job is None:
                self._json(404, {"error": "job not found or expired — "
                                          "please transcribe again"})
            else:
                self._json(200, _job_public(job))
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        _purge_old_jobs()
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
        filename = self.headers.get("X-Filename") or "upload.mp4"
        language = (self.headers.get("X-Language") or "zh").strip()
        suffix = os.path.splitext(filename)[1] or ".mp4"
        job_id = None  # set once a job owns the temp file (below)
        # Stream the upload straight to disk in 1 MB pieces — a large
        # video must never sit whole in RAM (0.5 GB limit).
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                tmp.write(chunk)
                remaining -= len(chunk)
            tmp.close()
            if remaining > 0:
                self._json(400, {"error": "upload incomplete — "
                                          "please try again"})
                return
            duration = probe_duration(tmp.name)
            if duration is not None and duration > MAX_AUDIO_S:
                log(f"Refused {filename}: {duration / 60:.1f} min "
                    f"(max {MAX_AUDIO_MINUTES} min)")
                self._json(400, {"error":
                                 f"វីដេអូនេះ {duration / 60:.1f} នាទី — "
                                 f"លើសកម្រិត {MAX_AUDIO_MINUTES} នាទី។ "
                                 f"សូមកាត់វីដេអូឱ្យខ្លីជាង "
                                 f"{MAX_AUDIO_MINUTES} នាទី "
                                 f"(video is {duration / 60:.1f} min, "
                                 f"max is {MAX_AUDIO_MINUTES} min)"})
                return
            job_id = uuid.uuid4().hex[:16]
            with _jobs_lock:
                _jobs[job_id] = {"status": "queued", "progress": 0,
                                 "srt": "", "cues": 0, "language": "",
                                 "error": "", "path": tmp.name,
                                 "language_req": language,
                                 "created": time.time()}
            _ensure_worker()
            _job_queue.put(job_id)
            log(f"Job {job_id} queued: {filename} ({length / 1e6:.1f} MB, "
                f"lang={language or 'auto'}, "
                f"duration={'?' if duration is None else f'{duration:.0f}s'})")
            self._json(202, {"job": job_id, "status": "queued"})
        except Exception as exc:  # noqa: BLE001 - report any failure to the app
            log(f"ERROR: {exc}")
            try:
                self._json(500, {"error": str(exc)})
            except Exception:
                pass
        finally:
            # Until a job owns the temp file, remove it here on every
            # error/early-return path; jobs delete their own file
            # when they finish.
            if job_id is None:
                _unlink(tmp.name)


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
        f"(model={WHISPER_MODEL}, max {MAX_AUDIO_MINUTES} min, "
        f"chunk {CHUNK_S}s)")
    log("Model loads on first transcribe (baked into the image).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Stopping.")
        server.shutdown()


if __name__ == "__main__":
    main()
