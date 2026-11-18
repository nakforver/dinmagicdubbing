const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Load the audio pipeline from the shipped bundle, without starting the UI.
const bundle = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const packed = bundle.match(/\}\)\((\[.*\]),(\[[\d,\s]+\])\);?\s*$/s);
assert.ok(packed, 'application bundle format');
const bytes = Buffer.from(JSON.parse(packed[1]).join(''), 'base64');
const key = JSON.parse(packed[2]);
const source = Buffer.from(bytes.map((value, i) =>
  (((value >>> 3) | (value << 5)) & 255) ^ key[i & 15] ^ ((i * 31) & 255)
)).toString('utf8');
function section(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, 'audio pipeline section: ' + start);
  return source.slice(a, b);
}
const decodeSource = section('const decode = ', 'function _0x1220(');
const audioSource = section('function _0x1231(', 'function _0x12a8(');
const exportSource = section('async function _0x1341(', "$('exp').onclick = ");

class AudioBuffer {
  constructor(channels, length, sampleRate) {
    this.numberOfChannels = channels;
    this.length = length;
    this.sampleRate = sampleRate;
    this.duration = length / sampleRate;
    this.channels = Array.from({ length: channels }, () => new Float32Array(length));
  }
  getChannelData(channel) { return this.channels[channel]; }
}

function wav(duration = 0.7, sampleRate = 8000) {
  const samples = Math.round(duration * sampleRate);
  const bytes = new ArrayBuffer(44 + samples * 2), view = new DataView(bytes);
  const write = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  write(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); write(8, 'WAVEfmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, 'data');
  view.setUint32(40, samples * 2, true);
  for (let i = 0; i < samples; i++) view.setInt16(44 + i * 2, 6553, true);
  return bytes;
}

function pipeline(rows, options = {}) {
  const stats = { decoded: 0, fetched: 0, logs: [], network: [] };
  const context = {
    createBuffer: (channels, length, sampleRate) => new AudioBuffer(channels, length, sampleRate),
    decodeAudioData(bytes, ok, no) {
      stats.decoded++;
      const result = Promise.resolve().then(() => {
        if (bytes.byteLength < 44) throw new Error('Invalid recorded audio');
        const view = new DataView(bytes), sr = view.getUint32(24, true);
        const buffer = new AudioBuffer(1, view.getUint32(40, true) / 2, sr);
        for (let i = 0; i < buffer.length; i++) buffer.channels[0][i] = view.getInt16(44 + i * 2, true) / 32768;
        return buffer;
      });
      result.then(ok, no);
      return result;
    }
  };
  const controls = {
    genv: { disabled: false }, voice: { value: 'edge' }, exp: { disabled: false },
    replay: { disabled: false }, go: { disabled: false }, goWrap: { hidden: true }
  };
  const fixture = { rows, context, videoDuration: options.videoDuration || 3, controls, stats };
  const sandbox = vm.createContext({
    fixture, setTimeout, clearInterval,
    fetch: async url => {
      stats.fetched++;
      stats.network.push(url);
      return { arrayBuffer: async () => url === 'blob:bad' ? new ArrayBuffer(0) : wav() };
    }
  });
  vm.runInContext(`
    let segs = fixture.rows;
    const v = { duration: fixture.videoDuration, pause() {} };
    const _mac = () => fixture.context;
    const sleep = () => Promise.resolve();
    const blog = message => fixture.stats.logs.push(message);
    const log = blog;
    const $ = id => fixture.controls[id];
    const window = { MediaRecorder: true };
    const MediaRecorder = { isTypeSupported: () => true };
    const HTMLCanvasElement = { prototype: { captureStream() {} } };
    const _0x1330 = async () => null;
    const _0x1176 = text => text;
    const _0x120f = async () => { throw new Error('Unexpected voice regeneration'); };
    const busy = () => {};
    const _0x12b9 = () => {};
    const _0x1495 = () => {};
    const active = new Set();
    ${decodeSource}
    ${audioSource}
    ${exportSource}
    globalThis.pipeline = { prepare: _0x1286, plan: _0x1297, mix: _0x1264, export: _0x1341 };
  `, sandbox);
  return { ...sandbox.pipeline, stats };
}

test('restored durations without AudioBuffers are decoded and fitted before export', async () => {
  const rows = [
    { t: 0, e: 0.4, km: 'សួស្ដី', audio: 'blob:first', dur: 0.7 },
    { t: 1, e: 1.4, km: 'សូមស្វាគមន៍', audio: 'blob:second', dur: 0.7 }
  ];
  const audio = pipeline(rows);
  const plan = await audio.plan();
  assert.equal(plan.length, 2, 'all restored voice lines remain in the export');
  assert.equal(audio.stats.decoded, 2);
  assert.ok(rows.every(row => row.buf && row.buf.duration > 0));
  assert.ok(plan[0].b.duration < rows[0].buf.duration, 'timing adjustment uses decoded audio');
  const mixed = await audio.mix(plan, 3, 8000);
  assert.ok(mixed.getChannelData(0).some(sample => sample > 0.1), 'merged output contains speech');
  await audio.plan();
  assert.equal(audio.stats.decoded, 2, 'valid buffers are reused');
});

test('all 246 cached voice lines survive preparation for a 57:17 video', async () => {
  const rows = Array.from({ length: 246 }, (_, i) => ({
    t: i * 3437 / 246, e: i * 3437 / 246 + 0.8,
    km: 'សួស្ដី', audio: 'blob:line-' + i, dur: 0.7
  }));
  const audio = pipeline(rows, { videoDuration: 3437 });
  const plan = await audio.plan();
  assert.equal(plan.length, 246);
  assert.equal(audio.stats.decoded, 246);
  assert.equal(audio.stats.fetched, 246);
  assert.ok(plan.every(clip => clip.b.getChannelData(0).length > 0));
});

test('an unreadable cached clip is excluded without losing valid clips', async () => {
  const rows = [
    { t: 0, e: 0.4, km: 'សួស្ដី', audio: 'blob:bad', dur: 0.7 },
    { t: 1, e: 2, km: 'សូមស្វាគមន៍', audio: 'blob:good', dur: 0.7 }
  ];
  const audio = pipeline(rows);
  const plan = await audio.plan();
  assert.equal(plan.length, 1);
  assert.equal(plan[0].i, 1);
  assert.equal(rows[0].buf, null);
  assert.equal(rows[0].dur, 0);
});

test('export stops with an actionable message if cached audio cannot be decoded', async () => {
  const audio = pipeline([{ t: 0, e: 1, km: 'សួស្ដី', audio: 'blob:bad', dur: 0.7 }]);
  await audio.export();
  assert.ok(audio.stats.logs.some(message => /Export stopped:/.test(message)));
  assert.ok(audio.stats.logs.some(message => /voice|audio/.test(message)));
  assert.ok(!audio.stats.logs.some(message => /TypeError|getChannelData/.test(message)));
});
