"""Download the Whisper tiny model into the image at build time.

Run by the railpack.json build step (HF_HOME points at /app/hf-cache,
so the model lands in the image and the runtime container never has to
download it from HuggingFace Hub). Kept as a file — instead of
`python -c "..."` — because Railpack's command parsing strips the
inner quotes of a -c one-liner.
"""
from faster_whisper import WhisperModel

WhisperModel("tiny")
print("tiny model downloaded into the image.")
