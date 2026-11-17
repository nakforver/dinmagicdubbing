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
                        "qwen_model": ...}
  POST /transcribe  -> body: raw media bytes (the video/audio file itself)
                       headers: X-Filename (original name, optional),
                                X-Language (e.g. zh, en, ko; empty = auto),
                                X-Engine (whisper | sensevoice | qwen3;
                                          default: whisper)
                       -> {"srt": "...", "language": "zh", "cues": 42}

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
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

WHISPER_MODEL = "medium"
QWEN_MODEL = "Qwen/Qwen3-ASR-0.6B-hf"
QWEN_CHUNK = 30  # seconds of audio per Qwen3-ASR generate call

ENGINES = ("whisper", "sensevoice", "qwen3")
ENGINE_INSTALL = {
    "whisper": "pip install faster-whisper",
    "sensevoice": "pip install funasr",
    "qwen3": 'pip install "transformers>=5.13.0" torch',
}

_models = {}  # engine name -> loaded model object(s)


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


def transcribe_whisper(path, language):
    model = get_whisper()
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


def transcribe_sensevoice(path, language):
    model = get_sensevoice()
    audio = load_audio_16k(path)
    duration = len(audio) / 16000.0
    lang = language or "auto"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    try:
        tmp.close()
        write_wav_16k(tmp.name, audio)
        res = model.generate(input=tmp.name, cache={}, language=lang,
                             use_itn=True, batch_size_s=60, merge_vad=True)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    item = res[0]
    text = (item.get("text") or "").strip()
    stamps = item.get("timestamp") or []
    sentences = split_sentences(text)
    cues = cues_from_timestamps(stamps, sentences)
    if not cues and text:
        cues = cues_from_text(text, 0.0, duration)
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


def transcribe_qwen3(path, language):
    processor, model, torch = get_qwen3()
    audio = load_audio_16k(path)
    duration = len(audio) / 16000.0
    lang = language or None  # None = auto-detect
    detected = lang or "zh"
    cues = []
    chunk_s = QWEN_CHUNK
    n_chunks = max(1, int((duration + chunk_s - 1) // chunk_s))
    for ci in range(n_chunks):
        start = ci * chunk_s
        end = min(duration, start + chunk_s)
        seg = audio[int(start * 16000):int(end * 16000)]
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
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        parsed = processor.decode(generated_ids,
                                  return_format="parsed")[0]
        text = (parsed.get("transcription") or "").strip()
        if parsed.get("language"):
            detected = _QWEN_LANG_NAMES.get(parsed["language"],
                                            parsed["language"])
        if not text:
            continue
        cues.extend(cues_from_text(text, start, end))
    srt, n = srt_from_cues(cues)
    return srt, detected, n


def transcribe_file(path, language, engine):
    if engine == "whisper":
        return transcribe_whisper(path, language)
    if engine == "sensevoice":
        return transcribe_sensevoice(path, language)
    if engine == "qwen3":
        return transcribe_qwen3(path, language)
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
        if self.path in ("/", "/healthz"):
            self._json(200, {"ok": True, "service": "whisper-transcribe",
                             "model": WHISPER_MODEL,
                             "engines": list(ENGINES),
                             "qwen_model": QWEN_MODEL})
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
        if engine not in ENGINES:
            self._json(400, {"error": f"unknown engine '{engine}' "
                                      f"(whisper/sensevoice/qwen3)"})
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
                f"lang={language or 'auto'}, engine={engine}) ...")
            srt, detected, n = transcribe_file(tmp.name, language, engine)
            log(f"Done: {n} cues, language={detected}, engine={engine}")
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
        f"http://{args.host}:{args.port}")
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
