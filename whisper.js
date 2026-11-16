// Whisper transcript via a local whisper-server.py — dinmagicdubbing.
// Sends the loaded video to the local Whisper server and fills #srtText
// with the transcript (.srt). The app's Translate Only mode then translates
// it to Khmer with Gemini, so no audio is ever sent to Gemini.
// The server must run on the same computer as this page is opened on
// (default http://127.0.0.1:8001). See whisper-server.py.
(function () {
  'use strict';
  var KEY = 'dinmagic_whisper_url';
  var urlInput = document.getElementById('whisperUrl');
  var langSel = document.getElementById('whisperLang');
  var btn = document.getElementById('whisperBtn');
  var statusEl = document.getElementById('whisperStatus');
  if (!urlInput || !btn || !statusEl) return;

  try {
    var saved = localStorage.getItem(KEY);
    if (saved) urlInput.value = saved;
  } catch (e) { /* storage unavailable */ }
  urlInput.addEventListener('change', function () {
    try { localStorage.setItem(KEY, urlInput.value.trim()); } catch (e) {}
  });

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
    setStatus('កំពុង transcribe… អាចត្រូវការពេលខ្លះ (វីដេអូ 9 នាទី ≈ 10–20 នាទី)។');
    try {
      var res = await fetch(base + '/transcribe', {
        method: 'POST',
        headers: {
          'X-Filename': encodeURIComponent(file.name),
          'X-Language': (langSel && langSel.value) || 'zh'
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
        ') — ជ្រើស Translate Only រួចចុច Dub។');
    } catch (err) {
      setStatus('មិនអាចភ្ជាប់ទៅ Whisper server បានទេ៖ ' + err.message +
        ' — សូមដំណើរការ whisper-server.py លើកុំព្យូទ័រ។');
    } finally {
      btn.disabled = false;
    }
  });
})();
