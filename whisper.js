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
// once on load (see below); requests time out after 30 min so the
// button can never freeze forever.
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
  var MIGRATED_KEY = 'dinmagic_whisper_url_migrated';
  var OLD_LOCAL_DEFAULT = 'http://127.0.0.1:8001';
  var cloudDefault = urlInput.defaultValue || urlInput.value;
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === OLD_LOCAL_DEFAULT && !localStorage.getItem(MIGRATED_KEY)) {
      saved = cloudDefault;
      try {
        localStorage.setItem(KEY, saved);
        localStorage.setItem(MIGRATED_KEY, '1');
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
    setStatus('កំពុង transcribe ជាមួយ ' + engineLabel() +
      '… អាចត្រូវការពេលខ្លះ (លើ Cloud វីដេអូ 9 នាទី ≈ 18 នាទី; លើកដំបូងត្រូវ load model ~2 នាទី)។');
    // 30-minute timeout: a warm 9-min video takes ~18 min on the cloud
    // plus ~2 min for the first model load, so the request must never
    // hang forever with the button disabled.
    var controller = new AbortController();
    var timeoutId = setTimeout(function () { controller.abort(); }, 30 * 60 * 1000);
    try {
      var res = await fetch(base + '/transcribe', {
        method: 'POST',
        headers: {
          'X-Filename': encodeURIComponent(file.name),
          'X-Language': (langSel && langSel.value) || 'zh',
          'X-Engine': engineName()
        },
        body: file,
        signal: controller.signal
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok) throw new Error((data && data.error) || ('HTTP ' + res.status));
      var srt = (data.srt || '').trim();
      if (!srt) throw new Error('server បានត្រឹម 0 បន្ទាត់');
      var box = document.getElementById('srtText');
      box.value = data.srt;
      box.dispatchEvent(new Event('input', { bubbles: true }));
      setStatus('បាន transcript ' + data.cues + ' បន្ទាត់ (' + (data.language || '') +
        ', ' + engineLabel() + ') — ជ្រើស Translate Only រួចចុច Dub។');
    } catch (err) {
      if (err && err.name === 'AbortError') {
        setStatus('ផុតពេល 30 នាទីហើយ — server មិនទាន់ឆ្លើយទេ។ សូមសាកម្តងទៀត ឬប្រើវីដេអូខ្លីជាងនេះ។');
      } else if (/127\.0\.0\.1|localhost/.test(base)) {
        setStatus('URL នេះគឺ localhost (127.0.0.1) — មានន័យថាទូរស័ព្ទ/កុំព្យូទ័រខ្លួនឯង ដែលគ្មាន server រត់នៅទីនោះទេ។ សូមប្តូរ URL ទៅ Cloud៖ ' + cloudDefault + ' ឬដំណើរការ whisper-server.py លើកុំព្យូទ័រ។');
      } else {
        setStatus('មិនអាចភ្ជាប់ទៅ server បានទេ៖ ' + err.message +
          ' — សូមពិនិត្យ URL ខាងលើ ឬដំណើរការ whisper-server.py លើកុំព្យូទ័រ។');
      }
    } finally {
      clearTimeout(timeoutId);
      btn.disabled = false;
    }
  });
})();
