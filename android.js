/* Presentation and Android navigation only; app.js owns dubbing and export. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const setup = byId('setupCard');
  const results = byId('resCard');
  const nav = byId('mobileNav');
  const narrow = window.matchMedia('(max-width: 940px)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const layoutKey = 'dinmagic_layout';
  let preferredLayout = 'auto';
  let returnFocus = null;
  let framePending = false;

  try { preferredLayout = localStorage.getItem(layoutKey) || 'auto'; } catch (_) {}
  if (!['auto', 'phone', 'desktop'].includes(preferredLayout)) preferredLayout = 'auto';

  function applyLayout() {
    const effective = preferredLayout === 'desktop' && narrow.matches ? 'phone' : preferredLayout;
    document.documentElement.classList.toggle('layout-phone', effective === 'phone');
    document.documentElement.classList.toggle('layout-desktop', effective === 'desktop');
    byId('layoutSeg').querySelectorAll('[data-layout]').forEach(button => {
      const selected = button.dataset.layout === effective;
      button.classList.toggle('on', selected);
      button.setAttribute('aria-pressed', String(selected));
      button.disabled = button.dataset.layout === 'desktop' && narrow.matches;
      button.setAttribute('aria-describedby', 'layoutHint');
    });
    resizeEditors();
  }
  byId('layoutSeg').addEventListener('click', event => {
    const button = event.target.closest('[data-layout]');
    if (!button || button.disabled) return;
    preferredLayout = button.dataset.layout;
    try { localStorage.setItem(layoutKey, preferredLayout); } catch (_) {}
    applyLayout();
  });
  narrow.addEventListener('change', applyLayout);

  function configured() {
    return Boolean((byId('en-gemini').checked && byId('key').value.trim()) || byId('srtText').value.trim());
  }
  function voiceLabel() {
    if (byId('voice').value === 'device') return 'សំឡេងឧបករណ៍';
    if (byId('voice').value === 'gemini') return 'Gemini voice';
    if (byId('evoice').value.includes('Piseth')) return 'Piseth';
    if (byId('evoice').value.includes('Sreymom')) return 'Sreymom';
    return 'សំឡេងស្វ័យប្រវត្តិ';
  }
  function updateSetup() {
    const source = byId('srtText').value.trim() ? 'អត្ថបទខ្មែរបានបញ្ចូល'
      : byId('en-gemini').checked && byId('key').value.trim() ? 'API Key បានបញ្ចូល'
      : 'បញ្ចូល API Key ឬអត្ថបទខ្មែរ';
    const text = source + ' · ' + voiceLabel();
    if (byId('setupState').textContent !== text) byId('setupState').textContent = text;
  }
  ['key', 'en-gemini', 'srtText', 'voice', 'evoice'].forEach(id => {
    byId(id).addEventListener('input', updateSetup);
    byId(id).addEventListener('change', updateSetup);
  });
  const importSubtitles = byId('srt').onchange;
  byId('srt').onchange = async event => {
    if (!event.target.files.length) return;
    try {
      await importSubtitles(event);
      updateSetup();
    } catch (_) {
      byId('studioHint').textContent = 'មិនអាចអានឯកសារអត្ថបទនេះបាន។ សូមជ្រើស .srt, .vtt ឬ .txt ម្ដងទៀត។';
    }
  };
  const tabs = [...setup.querySelectorAll('[data-tab]')];
  setup.querySelector('.tabs').setAttribute('role', 'tablist');
  setup.querySelector('.tabs').setAttribute('aria-label', 'API សំឡេង និងអត្ថបទ');
  function syncTabs() {
    tabs.forEach(button => {
      const active = button.classList.contains('on');
      button.id = 'setup-tab-' + button.dataset.tab;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', 'tab-' + button.dataset.tab);
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      const panel = byId('tab-' + button.dataset.tab);
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', button.id);
    });
  }
  tabs.forEach((button, index) => {
    button.addEventListener('click', syncTabs);
    button.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
        : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next === null) return;
      event.preventDefault();
      tabs[next].click();
      tabs[next].focus();
    });
  });

  function setCurrent(section) {
    nav.querySelectorAll('[data-jump]').forEach(button => {
      if (button.dataset.jump === section) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }
  function jump(section) {
    if (section === 'results' && results.hidden) return;
    let target;
    if (section === 'setup') {
      setup.open = true;
      target = setup.querySelector('summary');
    } else {
      if (configured()) setup.open = false;
      target = byId(section === 'results' ? 'resultsTitle' : 'uploadTitle');
    }
    setCurrent(section);
    target.scrollIntoView({ behavior: reducedMotion.matches ? 'auto' : 'smooth', block: 'start' });
    target.focus({ preventScroll: true });
  }
  nav.addEventListener('click', event => {
    const button = event.target.closest('[data-jump]');
    if (button && !button.disabled) jump(button.dataset.jump);
  });
  byId('setupContinue').addEventListener('click', () => jump('upload'));
  setup.addEventListener('toggle', () => {
    if (setup.open) setCurrent('setup');
  });
  byId('drop').addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      byId('drop').click();
    }
  });
  byId('go').addEventListener('click', event => {
    if (configured()) { byId('studioHint').textContent = ''; return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    byId('studioHint').textContent = 'សូមបញ្ចូល Gemini API Key ឬអត្ថបទខ្មែរ មុនចាប់ផ្ដើម។';
    jump('setup');
    setup.querySelector('[data-tab="prov"]').click();
  }, true);
  byId('vol').addEventListener('input', () => {
    byId('volumeValue').textContent = byId('vol').value + '%';
  });

  const translations = new Map([
    ['✨ Dub to Khmer', '✨ បញ្ចូលសំឡេងខ្មែរ'],
    ['📝 Translate to Khmer', '📝 បកប្រែជាខ្មែរ'],
    ['Full Dub', 'សំឡេង'],
    ['Translate Only', 'បកប្រែ'],
    ['🔊 Voice', '🔊 សំឡេង'],
    ['🔊 Generate Audio', '🔊 បង្កើតសំឡេង'],
    ['＋ Add key', '＋ បន្ថែម Key'],
    ['👁 Show', '👁 បង្ហាញ'],
    ['🙈 Hide', '🙈 លាក់'],
    ['✓ Check keys', '✓ ពិនិត្យ Key']
  ]);
  function syncActions() {
    ['go', 'goModeLbl', 'genv'].forEach(id => {
      const element = byId(id);
      const translated = translations.get(element.textContent.trim());
      if (translated) element.textContent = translated;
    });
    setup.querySelectorAll('.kctl button').forEach(button => {
      const translated = translations.get(button.textContent.trim());
      if (translated) button.textContent = translated;
    });
    setup.querySelectorAll('.keys input').forEach(input => {
      input.setAttribute('autocapitalize', 'none');
      input.setAttribute('autocorrect', 'off');
      input.setAttribute('aria-label', 'Gemini API Key');
    });
    byId('goModeBtn').setAttribute('aria-expanded', String(!byId('goMenu').hidden));
    const resultsButton = nav.querySelector('[data-jump="results"]');
    resultsButton.disabled = results.hidden;
    if (results.hidden && resultsButton.hasAttribute('aria-current')) setCurrent('upload');
    const count = results.hidden ? '' : byId('list').children.length + ' បន្ទាត់';
    if (byId('subtitleCount').textContent !== count) byId('subtitleCount').textContent = count;
    updateSetup();
    resizeEditors();
  }
  function scheduleSync() {
    if (framePending) return;
    framePending = true;
    requestAnimationFrame(() => { framePending = false; syncActions(); });
  }
  const observer = new MutationObserver(scheduleSync);
  ['resCard', 'go', 'goModeLbl', 'genv', 'goMenu', 'list', 'log'].forEach(id => {
    observer.observe(byId(id), { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
  });
  setup.querySelectorAll('.kctl').forEach(element => observer.observe(element, { childList: true, subtree: true }));
  setup.querySelectorAll('.keys').forEach(element => observer.observe(element, { childList: true }));

  function resizeEditors() {
    byId('list').querySelectorAll('.srow').forEach((row, index) => {
      const editor = row.querySelector('.km-ed');
      const timestamp = row.querySelector('.tsbtn');
      const gender = row.querySelector('.gbtn');
      const remove = row.querySelector('.delbtn');
      if (editor) {
        editor.setAttribute('aria-label', 'អត្ថបទខ្មែរ បន្ទាត់ទី ' + (index + 1));
        editor.style.height = 'auto';
        editor.style.height = Math.max(narrow.matches ? 72 : 28, editor.scrollHeight) + 'px';
      }
      if (timestamp) timestamp.setAttribute('aria-label', 'ទៅម៉ោង ' + timestamp.textContent.trim());
      if (gender) gender.setAttribute('aria-label', 'ប្ដូរសំឡេង បន្ទាត់ទី ' + (index + 1) + ': ' + gender.textContent.trim());
      if (remove) remove.setAttribute('aria-label', 'លុបបន្ទាត់ទី ' + (index + 1));
    });
  }
  byId('list').addEventListener('click', event => {
    const button = event.target.closest('.delbtn');
    if (!button || byId('list').children.length <= 1) return;
    if (!window.confirm('លុបបន្ទាត់អត្ថបទនេះ?')) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !byId('goMenu').hidden) {
      byId('goMenu').hidden = true;
      byId('goModeBtn').focus();
    }
  });

  const exportDialog = byId('xmod');
  function syncDialog() {
    const open = exportDialog.classList.contains('on') && !exportDialog.hidden;
    if (open && !document.body.classList.contains('modal-open')) {
      returnFocus = document.activeElement === document.body ? byId('exp') : document.activeElement;
      document.body.classList.add('modal-open');
      byId('xsave').focus();
    } else if (!open && document.body.classList.contains('modal-open')) {
      document.body.classList.remove('modal-open');
      if (returnFocus?.isConnected && !returnFocus.disabled && !returnFocus.closest('[hidden]')) {
        returnFocus.focus({ preventScroll: true });
      } else {
        byId(results.hidden ? 'uploadTitle' : 'resultsTitle').focus({ preventScroll: true });
      }
      returnFocus = null;
    }
  }
  new MutationObserver(syncDialog).observe(exportDialog, { attributes: true, attributeFilter: ['class', 'hidden'] });
  exportDialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const elements = [...exportDialog.querySelectorAll('a[href], button:not(:disabled)')].filter(element => !element.hidden);
    if (!elements.length) return;
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  const viewport = window.visualViewport;
  let normalHeight = viewport?.height || window.innerHeight;
  let viewportWidth = viewport?.width || window.innerWidth;
  function syncViewport() {
    const height = viewport?.height || window.innerHeight;
    const width = viewport?.width || window.innerWidth;
    const editing = document.activeElement?.matches('textarea, input:not([type="checkbox"]):not([type="range"]):not([type="file"])');
    if (Math.abs(width - viewportWidth) > 80) { normalHeight = height; viewportWidth = width; }
    if (!editing) normalHeight = Math.max(normalHeight, height);
    document.body.classList.toggle('keyboard-open', Boolean(editing && normalHeight - height > 120));
    document.documentElement.style.setProperty('--visual-height', height + 'px');
  }
  viewport?.addEventListener('resize', syncViewport);
  window.addEventListener('resize', () => { syncViewport(); scheduleSync(); });
  document.addEventListener('focusin', syncViewport);
  document.addEventListener('focusout', () => setTimeout(syncViewport, 0));

  // Hint under the Dub button: explain why it is disabled (no video yet).
  // Shows only when the button is disabled AND no video is loaded, so it
  // never appears while a dub is running.
  const goBtn = byId('go'), goHint = byId('goHint');
  function syncGoHint() {
    if (!goBtn || !goHint) return;
    const hasVideo = Boolean((byId('file').files && byId('file').files.length) || byId('v').src);
    goHint.hidden = !goBtn.disabled || hasVideo;
  }
  if (goBtn && goHint) {
    new MutationObserver(syncGoHint).observe(goBtn, { attributes: true, attributeFilter: ['disabled'] });
    byId('file').addEventListener('change', syncGoHint);
    syncGoHint();
  }

  // Delete the loaded video (the app has no built-in remove control).
  // Clears the picker, the preview and the results, and disables Dub so
  // the app cannot run on a stale video. Picking a new video works as before.
  const clearVideoBtn = byId('clearVideoBtn');
  if (clearVideoBtn) clearVideoBtn.addEventListener('click', () => {
    const file = byId('file'), v = byId('v');
    try { v.pause(); } catch (_) {}
    if (v.src && v.src.indexOf('blob:') === 0) { try { URL.revokeObjectURL(v.src); } catch (_) {} }
    v.removeAttribute('src');
    try { v.load(); } catch (_) {}
    file.value = '';
    file.dispatchEvent(new Event('change', { bubbles: true }));
    byId('stage').hidden = true;
    byId('dropTxt').textContent = 'ចុចដើម្បីជ្រើសវីដេអូ';
    byId('list').innerHTML = '';
    const resCard = byId('resCard'); if (resCard) resCard.hidden = true;
    const bar = byId('bar'); if (bar) bar.style.width = '0%';
    if (goBtn) goBtn.disabled = true;
    syncGoHint();
  });

  applyLayout();
  updateSetup();
  syncTabs();
  setup.open = !configured();
  setCurrent(setup.open ? 'setup' : 'upload');
  byId('volumeValue').textContent = byId('vol').value + '%';
  syncActions();
  syncDialog();
  syncViewport();
})();
