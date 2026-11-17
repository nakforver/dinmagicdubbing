#!/usr/bin/env python3
"""Local transcription server for dinmagicdubbing (Whisper / SenseVoice / Qwen3-ASR).

Run this on your computer (where the video files are):

    pip install faster-whisper            # for the Whisper engine
    pip install funasr                    # for the SenseVoice engine
    pip install "transformers>=5.13.0" torch   # for the Qwen3-ASR engine
    python3 whisper-server.py [--host 127.0.0.1] [--port 8001]
        [--model medium] [--qwen-model Qwen/Qwen3-ASR-0.6B-hf]

Then open the dinmagicdubbing app, go to the Subtitles tab, pick the
engine (Whisper / SenseVoice / Qwen3-ASR) and press "Transcribe".
The app sends the loaded video to this server, and the server fills the
subtitle box with the transcript (.srt). After that, choose Translate
Only in the app and Gemini translates it to Khmer. No audio is ever
sent to Gemini, so Gemini quota is saved.

Endpoints:
  GET  /healthz     -> {"ok": true, "service": "whisper-transcribe",
                        "model": ..., "engines": ["whisper","sensevoice","qwen3"],
                        "qwen_model": ..., "max_minutes": 60}
  POST /transcribe  -> body: raw media bytes (the video/audio file itself)
                       headers: X-Filename (original name, optional),
                                X-Language (e.g. zh, en, ko; empty = auto),
                                X-Engine (whisper | sensevoice | qwen3;
                                          default: whisper)
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
  browser/proxy request timeout (a 9-minute video is ~10-20 min with
  the medium model). The old single-request POST froze the app's
  button for the whole time. Now the upload returns immediately with
  a job id and the app polls for progress.

Why chunked transcription?
  Audio is decoded and transcribed in ~10-minute chunks
  (TRANSCRIBE_CHUNK_S, default 600 s) and the SRT cues are merged
  with offset timestamps — a whole long file is never decoded into
  one numpy array (2 h of 16 kHz float32 is ~460 MB). Maximum audio
  length is 60 minutes (MAX_AUDIO_MINUTES) — longer uploads are
  refused with a clear error naming the limit instead of running
  out of memory.

Notes:
  - Requires ffmpeg in PATH, plus the package for whichever engine you
    pick. Each engine's model loads lazily on FIRST USE, so the server
    starts even if only one engine's package is installed. If the
    requested engine's package is missing, the server answers with a
    clear error naming the pip install command.
  - The server only listens on localhost by default, so only your own
    computer can reach it. Use --host 0.0.0.0 only on a trusted network.
  - Audio is decoded with ffmpeg (not PyAV), so it works regardless of
    the installed PyAV version.
  - Whisper transcribes on CPU; a 9-minute video takes roughly 10-20
    minutes with the medium model. SenseVoice is much faster on CPU.
    Qwen3-ASR transcribes in 30-second chunks (it returns no
    timestamps, so cues are time slices of each chunk).
  - Only ONE job runs at a time (a FIFO queue + single worker thread):
    parallel transcriptions on one CPU would only slow each other
    down. Extra uploads wait in "queued" status.
"""
import argparse
import json
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

WHISPER_MODEL = "medium"
QWEN_MODEL = "Qwen/Qwen3-ASR-0.6B-hf"
QWEN_CHUNK = 30  # seconds of audio per Qwen3-ASR generate call
# Audio is transcribed in chunks of this many seconds (default 10 min);
# override for tests (e.g. TRANSCRIBE_CHUNK_S=30). One chunk of mono
# 16 kHz float32 is ~38 MB at 600 s.
CHUNK_S = int(os.environ.get("TRANSCRIBE_CHUNK_S", "600"))
MAX_AUDIO_MINUTES = 60
MAX_AUDIO_S = MAX_AUDIO_MINUTES * 60
JOB_TTL_S = 2 * 3600  # finished jobs (and their SRT) are kept 2 hours

ENGINES = ("whisper", "sensevoice", "qwen3")
ENGINE_INSTALL = {
    "whisper": "pip install faster-whisper",
    "sensevoice": "pip install funasr",
    "qwen3": 'pip install "transformers>=5.13.0" torch',
}

_models = {}  # engine name -> loaded model object(s)

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
    path, language, engine = (job["path"], job["language_req"],
                              job["engine"])
    try:
        _set_job(jid, status="loading", progress=5)
        srt, detected, n = transcribe_file(
            path, language, engine,
            lambda frac: _set_job(
                jid, status="processing",
                progress=20 + int(75 * max(0.0, min(1.0, frac or 0.0)))))
        _set_job(jid, status="done", progress=100, srt=srt, cues=n,
                 language=detected)
        log(f"job {jid} done: {n} cues, language={detected}, "
            f"engine={engine}")
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


def probe_duration(path):
    """Total audio duration in seconds via `ffmpeg -i`, or None if unknown."""
    try:
        proc = subprocess.run(["ffmpeg", "-i", path],
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
    cmd = ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(length),
           "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.check_output(cmd)
    return np.frombuffer(raw, dtype=np.float32)


def iter_audio_chunks(path, duration=None):
    """Yield (start_s, float32 mono 16 kHz samples) per CHUNK_S seconds.

    Only one chunk (~38 MB at 600 s) is ever in memory, so a 60-minute
    file never blows up RAM. When the duration is unknown the loop
    decodes until EOF.
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


def _check_max(processed):
    if processed > MAX_AUDIO_S:
        raise ValueError(
            f"audio លើស {MAX_AUDIO_MINUTES} នាទី — សូមកាត់វីដេអូឱ្យខ្លីជាង "
            f"{MAX_AUDIO_MINUTES} នាទី (audio over {MAX_AUDIO_MINUTES} min)")


def write_wav_16k(path, audio):
    """Write mono 16 kHz float32 samples to a 16-bit PCM WAV file."""
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
    """Split a long sentence into <= max_chars pieces (hard split)."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def cues_from_text(text, start_s, end_s):
    """Build SRT cues for text spanning [start_s, end_s] (no timestamps
    from the model). Sentences are spread over the window in proportion
    to their character length; long sentences are split so no cue is
    much longer than ~10 s."""
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


def cues_from_timestamps(stamps, sentences):
    """Pair SenseVoice timestamp chunks [(start_ms, end_ms), ...] with
    the sentences from the punctuation model. Returns a list of
    (start_s, end_s, text)."""
    cues = []
    if stamps and len(stamps) == len(sentences):
        cues = [(st / 1000.0, en / 1000.0, sent)
                for (st, en), sent in zip(stamps, sentences)]
    elif stamps:
        for i, (st, en) in enumerate(stamps):
            chunk = sentences[i] if i < len(sentences) else ""
            if chunk:
                cues.append((st / 1000.0, en / 1000.0, chunk))
        if len(sentences) > len(stamps) and cues:
            st, en, last = cues[-1]
            cues[-1] = (st, en, last + "".join(sentences[len(stamps):]))
    return cues


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


# ---------------------------------------------------------------- engines

def get_whisper():
    if "whisper" not in _models:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper មិនទាន់ដំឡើងទេ — run: pip install faster-whisper")
        log(f"Loading Whisper model '{WHISPER_MODEL}' ...")
        _models["whisper"] = WhisperModel(WHISPER_MODEL, device="auto",
                                          compute_type="auto")
        log("Whisper model ready.")
    return _models["whisper"]


def transcribe_whisper(path, language, progress_cb=None):
    """Transcribe in CHUNK_S pieces, merging cues with offset timestamps.

    progress_cb(frac) is called after each chunk with the fraction of
    the audio processed so far. The language detected on the first
    chunk is reused for later chunks so one clip never flips language
    mid-way.
    """
    model = get_whisper()
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
        _check_max(processed)
        if progress_cb is not None:
            progress_cb(processed / duration if duration else None)
    srt, n = srt_from_cues(cues)
    if n == 0:
        raise ValueError("no speech found in the uploaded file")
    return srt, detected or language or "zh", n


def get_sensevoice():
    if "sensevoice" not in _models:
        try:
            from funasr import AutoModel
        except ImportError:
            raise RuntimeError(
                "FunASR មិនទាន់ដំឡើងទេ — run: pip install funasr")
        log("Loading SenseVoiceSmall ... (first run downloads the models)")
        _models["sensevoice"] = AutoModel(
            model="iic/SenseVoiceSmall", vad_model="fsmn-vad",
            punc_model="ct-punc", device="cpu")
        log("SenseVoice model ready.")
    return _models["sensevoice"]


def transcribe_sensevoice(path, language, progress_cb=None):
    """SenseVoice in CHUNK_S pieces, merging cues with offset timestamps."""
    model = get_sensevoice()
    duration = probe_duration(path)
    lang = language or "auto"
    cues = []
    processed = 0.0
    for start, audio in iter_audio_chunks(path, duration):
        if audio.size == 0:
            continue
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        try:
            tmp.close()
            write_wav_16k(tmp.name, audio)
            res = model.generate(input=tmp.name, cache={}, language=lang,
                                 use_itn=True, batch_size_s=60, merge_vad=True)
        finally:
            _unlink(tmp.name)
        item = res[0]
        text = (item.get("text") or "").strip()
        stamps = item.get("timestamp") or []
        sentences = split_sentences(text)
        chunk_cues = cues_from_timestamps(stamps, sentences)
        if not chunk_cues and text:
            chunk_cues = cues_from_text(text, 0.0, len(audio) / 16000.0)
        cues.extend((st + start, en + start, t)
                    for st, en, t in chunk_cues)
        processed = start + len(audio) / 16000.0
        _check_max(processed)
        if progress_cb is not None:
            progress_cb(processed / duration if duration else None)
    srt, n = srt_from_cues(cues)
    return srt, language or "zh", n


_QWEN_LANG_NAMES = {
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


def get_qwen3():
    if "qwen3" not in _models:
        try:
            import torch
            from transformers import (AutoModelForMultimodalLM,
                                      AutoProcessor)
        except ImportError:
            raise RuntimeError(
                "transformers/torch មិនទាន់ដំឡើងទេ — run: "
                'pip install "transformers>=5.13.0" torch')
        log(f"Loading Qwen3-ASR model '{QWEN_MODEL}' ... "
            "(first run downloads ~1.2 GB)")
        processor = AutoProcessor.from_pretrained(QWEN_MODEL)
        model = AutoModelForMultimodalLM.from_pretrained(
            QWEN_MODEL, dtype=torch.float32, device_map="auto")
        _models["qwen3"] = (processor, model, torch)
        log("Qwen3-ASR model ready.")
    return _models["qwen3"]


def transcribe_qwen3(path, language, progress_cb=None):
    """Qwen3-ASR in CHUNK_S pieces (each split into 30 s slices as
    before), merging cues with offset timestamps."""
    processor, model, torch = get_qwen3()
    duration = probe_duration(path)
    lang = language or None  # None = auto-detect
    detected = lang or "zh"
    cues = []
    processed = 0.0
    for chunk_start, audio in iter_audio_chunks(path, duration):
        if audio.size == 0:
            continue
        chunk_dur = len(audio) / 16000.0
        n_slices = max(1, int(math.ceil(chunk_dur / QWEN_CHUNK)))
        for si in range(n_slices):
            s0 = si * QWEN_CHUNK
            s1 = min(chunk_dur, s0 + QWEN_CHUNK)
            seg = audio[int(s0 * 16000):int(s1 * 16000)]
            if seg.size == 0:
                continue
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
                _unlink(tmp.name)
            generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
            parsed = processor.decode(generated_ids,
                                      return_format="parsed")[0]
            text = (parsed.get("transcription") or "").strip()
            if parsed.get("language"):
                detected = _QWEN_LANG_NAMES.get(parsed["language"],
                                                parsed["language"])
            if not text:
                continue
            cues.extend(cues_from_text(text, chunk_start + s0,
                                       chunk_start + s1))
        processed = chunk_start + chunk_dur
        _check_max(processed)
        if progress_cb is not None:
            progress_cb(processed / duration if duration else None)
    srt, n = srt_from_cues(cues)
    return srt, detected, n


def transcribe_file(path, language, engine, progress_cb=None):
    if engine == "whisper":
        return transcribe_whisper(path, language, progress_cb)
    if engine == "sensevoice":
        return transcribe_sensevoice(path, language, progress_cb)
    if engine == "qwen3":
        return transcribe_qwen3(path, language, progress_cb)
    raise ValueError(f"unknown engine: {engine}")


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
            self._json(200, {"ok": True, "service": "whisper-transcribe",
                             "model": WHISPER_MODEL,
                             "engines": list(ENGINES),
                             "qwen_model": QWEN_MODEL,
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
        if engine not in ENGINES:
            self._json(400, {"error": f"unknown engine '{engine}' "
                                      f"(whisper/sensevoice/qwen3)"})
            return
        filename = self.headers.get("X-Filename") or "upload.mp4"
        language = (self.headers.get("X-Language") or "zh").strip()
        suffix = os.path.splitext(filename)[1] or ".mp4"
        job_id = None  # set once a job owns the temp file (below)
        # Stream the upload straight to disk in 1 MB pieces — a large
        # video must never sit whole in RAM.
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
                                 "engine": engine,
                                 "created": time.time()}
            _ensure_worker()
            _job_queue.put(job_id)
            log(f"Job {job_id} queued: {filename} ({length / 1e6:.1f} MB, "
                f"lang={language or 'auto'}, engine={engine}, "
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
    global WHISPER_MODEL, QWEN_MODEL, QWEN_CHUNK
    ap = argparse.ArgumentParser(
        description="Local transcription server for dinmagicdubbing "
                    "(Whisper / SenseVoice / Qwen3-ASR)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--model", default="medium",
                    help="whisper model: tiny/base/small/medium/large-v3")
    ap.add_argument("--qwen-model", default="Qwen/Qwen3-ASR-0.6B-hf",
                    help="Qwen3-ASR model id (default: Qwen/Qwen3-ASR-0.6B-hf; "
                         "1.7B: Qwen/Qwen3-ASR-1.7B-hf)")
    ap.add_argument("--qwen-chunk", type=int, default=30,
                    help="seconds of audio per Qwen3-ASR call (default: 30)")
    args = ap.parse_args()
    WHISPER_MODEL = args.model
    QWEN_MODEL = args.qwen_model
    QWEN_CHUNK = args.qwen_chunk
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"Local transcription server listening on "
        f"http://{args.host}:{args.port} "
        f"(max {MAX_AUDIO_MINUTES} min, chunk {CHUNK_S}s)")
    log("Engines load on first use: whisper (pip install faster-whisper), "
        "sensevoice (pip install funasr), "
        'qwen3 (pip install "transformers>=5.13.0" torch).')
    log("In the app: Subtitles tab -> pick engine -> Transcribe.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Stopping.")
        server.shutdown()


if __name__ == "__main__":
    main()
