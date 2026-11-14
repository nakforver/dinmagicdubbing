# dinmagicdubbing implementation plan

## Scope

Turn the existing MT Dubber Free frontend into a runnable local website that supports the complete browser workflow: choose a local video, transcribe and translate with Gemini, generate Khmer voice with Edge or Gemini, align and mix audio, and export the final MP4/WebM file in the browser.

## Implementation decisions

- Preserve the existing UI and browser-side media pipeline instead of replacing the working dubbing logic.
- Add a small Python server with a health endpoint so the project has a repeatable local start command and a clear readiness check.
- Keep video processing client-side; the local server only serves static files and health status.
- Keep external provider calls explicit in the UI: Gemini requires a user-supplied key, while Edge uses the configured Khmer TTS helper URL.
- Add a route manifest and documentation so the project is easy to preview and maintain.

## Project structure

- `index.html`: application shell and controls.
- `app.js`: browser dubbing, TTS, audio mixing, and export pipeline.
- `style.css`: visual styling.
- `server.py`: local HTTP server and `/healthz` endpoint.
- `manus-routes.json`: declared website page routes.
- `docs/API.md`: provider API and voice-dubbing integration documentation.

## Done when

The site starts with one command, returns a healthy response, opens the dubbing UI, accepts a local video, supports the configured provider flow, creates browser-side audio, and offers a final MP4/WebM download when the browser supports the required media APIs. Missing provider keys, unreachable helpers, unsupported browsers, and export failures must be shown as actionable messages rather than silent failures.
