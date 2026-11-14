# TODO

## Local runnable website

- Start the website with `python3 server.py` or `PORT=8000 python3 server.py`.
- Serve the application entrypoint and static assets from the project root.
- Provide `GET /healthz` with an unauthenticated `200` JSON response.

## Complete dubbing flow

- Accept local MP4, MOV, and WebM video files in the browser.
- Use a Gemini API key supplied in the Providers section for transcription and Khmer translation.
- Generate Khmer speech with the configured Edge helper or Gemini audio mode.
- Preserve subtitle timing and speaker gender while generating voice clips.
- Mix Khmer voice with optional original audio in the browser.
- Export the final dubbed video as MP4 or WebM when the browser supports WebCodecs/MediaRecorder.
- Download the final output to the user-selected location or browser Downloads folder.

## Failure handling

- Show a clear message when Gemini credentials are missing or invalid.
- Show a clear message when the Edge helper is unavailable or blocked by CORS.
- Explain when the browser cannot export video and recommend Chrome or Edge.
- Prevent silent export when no audio clip was generated.

## Documentation and delivery

- Keep `docs/API.md` synchronized with provider endpoints and request/response formats.
- Keep `README.md` synchronized with local run and troubleshooting instructions.
- Verify the local health endpoint and commit the runnable changes to `main`.
