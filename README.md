# dinmagicdubbing

Browser-based AI video dubbing tool for Khmer voiceover.

## Run locally

```bash
python3 server.py
```

Open <http://127.0.0.1:8000> in a browser.

The server also exposes a readiness endpoint at <http://127.0.0.1:8000/healthz>.
To use another port, run `PORT=8080 python3 server.py`.

## Notes

- Add a Gemini API key in the Providers section for transcription and translation.
- Edge and Gemini voice generation use the services configured in `app.js`.
- Video export is performed in the browser.
- Use Chrome or Edge for the best WebCodecs/MediaRecorder export support.
- For a complete run, choose Edge or Gemini voice rather than the device-only voice; device speech synthesis cannot be recorded into an exported video.

## Documentation

- [Voice Dubbing API Documentation](docs/API.md)
