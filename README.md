# dinmagicdubbing

Browser-based AI video dubbing tool for Khmer voiceover.

## Run locally

```bash
python3 -m http.server 8000
```

Open <http://127.0.0.1:8000> in a browser.

## Notes

- Add a Gemini API key in the Providers section for transcription and translation.
- Edge and Gemini voice generation use the services configured in `app.js`.
- Video export is performed in the browser.

## Documentation

- [Voice Dubbing API Documentation](docs/API.md)
