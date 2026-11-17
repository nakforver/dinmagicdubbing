// Whisper / SenseVoice / Qwen3-ASR transcript via a transcription server
// — dinmagicdubbing.
// Sends the loaded video to the transcription server and fills #srtText
// with the transcript (.srt). The app's Translate Only mode then
// translates it to Khmer with Gemini, so no audio is ever sent to Gemini.
// Default server is the free cloud server on Cloady (JPN1, Whisper tiny)
// so the phone can transcribe too; the URL field stays editable — put
// http://127.0.0.1:8001 there to use whisper-server.py (medium) on your
// own computer instead, which is faster and more accurate.
// SenseVoice / Qwen3-ASR only exist on the local server; the cloud
// server answers 400 for those engines.
// A stale localhost default saved before the cloud switch is migrated
// once on load (see below).
//
// How a transcribe runs (async jobs, 2026-11-17):
//   1. The video is uploaded with XMLHttpRequest so upload progress
//      can be shown ("កំពុង upload… 35%") — a large video upload no
//      longer looks frozen.
//   2. The server answers 202 {"job": "<id>"} immediately and
//      transcribes in the background (in ~10-min chunks, max 60 min).
//   3. This script polls GET /job/<id> every 10 s and shows the
//      server's progress, until the job is done (or errors). Overall
//      cap is 2 hours. Old servers that answer 200 {"srt": ...}
//      directly are still handled (treated as done immediately).
(function () {
  'use strict';
  var KEY = 'dinmagic_whisper_url';
  var ENGINE_KEY = 'dinmagic_whisper_engine';
  var ENGINE_LABELS = { whisper: 'Whisper', sensevoice: 'SenseVoice', qwen3: 'Qwen3-ASR' };
  var urlInput = document.getElementById('whisperUrl');
  var langSel = document.getElementById('whisperLang');
  var engineSel = document.getElementById('whisperEngine');
  var btn = document.getElementById('whisperBtn');
  var statusEl = document.getElementById('whisperStatus');
  if (!urlInput || !btn || !statusEl) return;

  function engineName() { return (engineSel && engineSel.value) || 'whisper'; }
  function engineLabel() { return ENGINE_LABELS[engineName()] || 'Whisper'; }
  function updateBtnLabel() {
    btn.textContent = '🎙️ Transcribe with ' + engineLabel();
  }

  // Migration (2026-11-17): phones that used the app before the free
  // cloud server became the default still carry the OLD default
  // 'http://127.0.0.1:8001' in localStorage — on a phone that means the
  // phone itself, where no server listens, so "Transcribe with Whisper"
  // froze. Migrate that stale value once to the cloud default (the
  // input's HTML default value) and remember it, so a deliberate
  // localhost choice made afterwards is never overwritten again.
  // The cloud server itself was recreated once (2026-11-17, async-job
  // redeploy), which changed its URL — so a saved copy of the OLD
  // cloud URL is migrated once too, under a second flag.
  var MIGRATED_KEY = 'dinmagic_whisper_url_migrated';
  var MIGRATED2_KEY = 'dinmagic_whisper_url_migrated2';
  var OLD_LOCAL_DEFAULT = 'http://127.0.0.1:8001';
  var OLD_CLOUD_URL = 'https://dinmagic-whisper-cgpozr1p-nakforver.cloady.io';
  var cloudDefault = urlInput.defaultValue || urlInput.value;
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === OLD_LOCAL_DEFAULT && !localStorage.getItem(MIGRATED_KEY)) {
      saved = cloudDefault;
      try {
        localStorage.setItem(KEY, saved);
        localStorage.setItem(MIGRATED_KEY, '1');
      } catch (e2) {}
    } else if (saved === OLD_CLOUD_URL && !localStorage.getItem(MIGRATED2_KEY)) {
      saved = cloudDefault;
      try {
        localStorage.setItem(KEY, saved);
        localStorage.setItem(MIGRATED2_KEY, '1');
      } catch (e2) {}
    }
    if (saved) urlInput.value = saved;
    var savedEngine = localStorage.getItem(ENGINE_KEY);
    if (savedEngine && engineSel && ENGINE_LABELS[savedEngine]) {
      engineSel.value = savedEngine;
    }
  } catch (e) { /* storage unavailable */ }
  urlInput.addEventListener('change', function () {
    try { localStorage.setItem(KEY, urlInput.value.trim()); } catch (e) {}
  });
  if (engineSel) {
    engineSel.addEventListener('change', function () {
      try { localStorage.setItem(ENGINE_KEY, engineSel.value); } catch (e) {}
      updateBtnLabel();
    });
  }
  updateBtnLabel();

  function setStatus(text) { statusEl.textContent = text; }

  function parseJson(text) {
    try { return JSON.parse(text || '{}'); } catch (e) { return {}; }
  }

  // Upload with XMLHttpRequest so the upload itself reports progress.
  // Resolves with the parsed JSON body: either {"srt": ...} (old
  // server, done immediately) or {"job": "<id>"} (new server, poll it).
  // Rejects with an Error whose message is the server's error text,
  // or 'Failed to fetch' when the server cannot be reached at all.
  function postTranscribe(base, file, lang, engine, onUpload) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', base + '/transcribe', true);
      xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
      xhr.setRequestHeader('X-Language', lang);
      xhr.setRequestHeader('X-Engine', engine);
      // No timeout on the upload itself: a large video over mobile
      // data can legitimately take a long time. The overall 2-hour
      // cap below covers the whole transcribe.
      xhr.timeout = 0;
      if (xhr.upload) {
        xhr.upload.onprogress = function (ev) {
          if (ev.lengthComputable && ev.total > 0) {
            onUpload(Math.round(ev.loaded / ev.total * 100));
          } else {
            onUpload(-1);
          }
        };
      }
      xhr.onload = function () {
        var data = parseJson(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error((data && data.error) || ('HTTP ' + xhr.status)));
      };
      xhr.onerror = function () { reject(new Error('Failed to fetch')); };
      xhr.ontimeout = function () { reject(new Error('Failed to fetch')); };
      xhr.send(file);
    });
  }

  // Poll GET /job/<id> every 10 s until done/error. Each poll has a
  // short 15 s timeout; a slow or failed poll is retried, so a shaky
  // mobile connection does not kill a long transcribe. Overall cap is
  // 2 hours from the moment the button was pressed.
  // Rejects with an Error carrying .kind: 'joberror' (the server's
  // error text), 'job404' (job unknown — old whisper-server.py), or
  // 'timeout' (2-hour cap). onProgress(progress, status) reports the
  // server's progress for the status line.
  function pollJob(base, jobId, startedAt, onProgress) {
    var POLL_MS = 10000;
    var POLL_TIMEOUT_MS = 15000;
    var OVERALL_CAP_MS = 2 * 60 * 60 * 1000;
    function fail(kind, message) {
      var err = new Error(message);
      err.kind = kind;
      return err;
    }
    return new Promise(function (resolve, reject) {
      function tick() {
        if (Date.now() - startedAt > OVERALL_CAP_MS) {
          reject(fail('timeout', ''));
          return;
        }
        var controller = new AbortController();
        var timeoutId = setTimeout(function () { controller.abort(); }, POLL_TIMEOUT_MS);
        fetch(base + '/job/' + encodeURIComponent(jobId), { signal: controller.signal })
          .then(function (res) {
            clearTimeout(timeoutId);
            if (res.status === 404) throw fail('job404', '');
            return res.json().catch(function () { return {}; });
          })
          .then(function (data) {
            if (!data || typeof data !== 'object') throw fail('joberror', 'server ឆ្លើយមកមិនស្គាល់');
            if (data.status === 'done') resolve(data);
            else if (data.status === 'error') reject(fail('joberror', data.error || 'server error'));
            else {
              onProgress(data.progress || 0, data.status || 'processing');
              setTimeout(tick, POLL_MS);
            }
          })
          .catch(function (err) {
            clearTimeout(timeoutId);
            if (err && (err.kind === 'job404' || err.kind === 'joberror' || err.kind === 'timeout')) {
              reject(err);
            } else {
              // Poll failed (slow network, aborted poll, bad JSON):
              // keep polling — the job continues on the server.
              setTimeout(tick, POLL_MS);
            }
          });
      }
      tick();
    });
  }

  function finish(data) {
    var srt = (data.srt || '').trim();
    if (!srt) throw new Error('server បានត្រឹម 0 បន្ទាត់');
    var box = document.getElementById('srtText');
    box.value = data.srt;
    box.dispatchEvent(new Event('input', { bubbles: true }));
    setStatus('បាន transcript ' + data.cues + ' បន្ទាត់ (' + (data.language || '') +
      ', ' + engineLabel() + ') — ជ្រើស Translate Only រួចចុច Dub។');
  }

  btn.addEventListener('click', async function () {
    var fileInput = document.getElementById('file');
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (!file) {
      setStatus('សូមជ្រើសវីដេអូជាមុនសិន (ជំហាន 2)។');
      return;
    }
    var base = urlInput.value.trim().replace(/\/+$/, '');
    if (!base) {
      setStatus('សូមបញ្ចូល Whisper server URL។');
      return;
    }
    try { localStorage.setItem(KEY, base); } catch (e) {}
    btn.disabled = true;
    var startedAt = Date.now();
    setStatus('កំពុង upload… 0%');
    try {
      var data = await postTranscribe(
        base, file, (langSel && langSel.value) || 'zh', engineName(),
        function (pct) {
          setStatus(pct >= 0 ? 'កំពុង upload… ' + pct + '%'
                             : 'កំពុង upload…');
        });
      if (data.srt) {
        // Old server (whisper-server.py before the job update):
        // the transcript came back directly with the upload.
        finish(data);
        return;
      }
      if (!data.job) throw new Error('server ឆ្លើយមកមិនស្គាល់');
      setStatus('បាន upload រួច — កំពុងរង់ចាំ server ចាប់ផ្តើម…');
      var job = await pollJob(base, data.job, startedAt, function (pct, st) {
        setStatus(st === 'loading' ? 'កំពុង load model…'
                  : st === 'queued' ? 'បាន upload រួច — កំពុងរង់ចាំ server…'
                  : 'កំពុង transcribe… ' + pct + '%');
      });
      finish(job);
    } catch (err) {
      if (err && err.kind === 'job404') {
        setStatus('Server ចាស់ពេក មិនស្គាល់ job នេះទេ — សូម update whisper-server.py លើកុំព្យូទ័រ (git pull) រួចដំណើរការវាឡើងវិញ។');
      } else if (err && err.kind === 'timeout') {
        setStatus('ផុតពេល 2 ម៉ោងហើយ — server មិនទាន់ឆ្លើយទេ។ សូមសាកម្តងទៀត ឬប្រើវីដេអូខ្លីជាងនេះ។');
      } else if (err && err.kind === 'joberror') {
        setStatus(err.message);
      } else if (/127\.0\.0\.1|localhost/.test(base)) {
        setStatus('URL នេះគឺ localhost (127.0.0.1) — មានន័យថាទូរស័ព្ទ/កុំព្យូទ័រខ្លួនឯង ដែលគ្មាន server រត់នៅទីនោះទេ។ សូមប្តូរ URL ទៅ Cloud៖ ' + cloudDefault + ' ឬដំណើរការ whisper-server.py លើកុំព្យូទ័រ។');
      } else {
        setStatus('មិនអាចភ្ជាប់ទៅ server បានទេ៖ ' + err.message +
          ' — សូមពិនិត្យ URL ខាងលើ ឬដំណើរការ whisper-server.py លើកុំព្យូទ័រ។');
      }
    } finally {
      btn.disabled = false;
    }
  });
})();
