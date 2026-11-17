// Whisper / SenseVoice / Qwen3-ASR transcript via a local whisper-server.py
// — dinmagicdubbing.
// Sends the loaded video to the local transcription server and fills
// #srtText with the transcript (.srt). The app's Translate Only mode then
// translates it to Khmer with Gemini, so no audio is ever sent to Gemini.
// The server must run on the same computer as this page is opened on
// (default http://127.0.0.1:8001). See whisper-server.py.
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

  try {
    var saved = localStorage.getItem(KEY);
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
      '… អាចត្រូវការពេលខ្លះ (វីដេអូ 9 នាទី ≈ 10–20 នាទីជាមួយ Whisper)។');
    try {
      var res = await fetch(base + '/transcribe', {
        method: 'POST',
        headers: {
          'X-Filename': encodeURIComponent(file.name),
          'X-Language': (langSel && langSel.value) || 'zh',
          'X-Engine': engineName()
        },
        body: file
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
      setStatus('មិនអាចភ្ជាប់ទៅ local server បានទេ៖ ' + err.message +
        ' — សូមដំណើរការ whisper-server.py លើកុំព្យូទ័រ។');
    } finally {
      btn.disabled = false;
    }
  });
})();
