// Real local-model API + Chromium playback probe. Start scripts/probe-tts.py --serve first.
// Usage: node scripts/probe-tts.mjs [playwright-package-path] [browser-channel]
/* global window, document */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)(process.argv[2] || 'playwright');
const server = await createServer({
  configFile: false, logLevel: 'error', root: fileURLToPath(new URL('..', import.meta.url)),
  resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 5189, hmr: false,
    proxy: { '/api/speech': { target: 'http://127.0.0.1:5190', headers: { 'X-Magi-Client-Id': 'browser-probe' } } } },
});
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ ...(process.argv[3] ? { channel: process.argv[3] } : {}), headless: true, args: ['--mute-audio'] });
  const page = await browser.newPage();
  await page.route('**/tts-probe', (route) => route.fulfill({ contentType: 'text/html', body: '<button id="start">Start</button><button id="pause">Pause</button><button id="stop">Stop</button>' }));
  await page.goto(`${server.resolvedUrls.local[0]}tts-probe`);
  await page.evaluate(async () => {
    const { SegmentAudioPlayer } = await import('/src/lib/audio/player.ts');
    const { TTSController } = await import('/src/lib/audio/tts-controller.ts');
    const base = '/api/speech/tts';
    const call = async (path, method = 'GET', body, signal) => {
      const result = await fetch(base + path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined, signal });
      if (!result.ok) throw new Error(await result.text());
      return result;
    };
    const api = {
      create: async (request_id, source, signal) => { window.requestId = request_id; return (await call('/syntheses', 'POST', { request_id, source }, signal)).json(); },
      byRequest: async (id, signal) => (await call(`/syntheses/by-request/${id}`, 'GET', undefined, signal)).json(),
      get: async (id, signal) => (await call(`/syntheses/${id}`, 'GET', undefined, signal)).json(),
      advance: async (id, seq, signal) => { window.admitted.push(seq); return (await call(`/syntheses/${id}/segments/${seq}`, 'POST', {}, signal)).json(); },
      audio: async (id, seq, signal) => (await call(`/syntheses/${id}/segments/${seq}`, 'GET', undefined, signal)).arrayBuffer(),
      cancel: async (id) => (await call(`/syntheses/by-request/${id}/cancel`, 'POST', {})).json(),
    };
    window.admitted = [];
    window.player = new SegmentAudioPlayer(); window.controller = new TTSController(window.player, api);
    document.querySelector('#start').onclick = () => { window.admitted = []; void window.controller.speak({ kind: 'text', text: '你好，这是本地模型。Hello, this is Magi.谢谢，再见。' }); };
    document.querySelector('#pause').onclick = () => { void window.controller.pause(); };
    document.querySelector('#stop').onclick = () => window.controller.stop();
  });
  await page.click('#start');
  await page.waitForFunction(() => window.controller.getSnapshot().phase === 'playing', undefined, { timeout: 30000 });
  await page.click('#pause');
  await page.waitForFunction(() => window.controller.getSnapshot().phase === 'paused');
  const count = await page.evaluate(() => window.admitted.length);
  await new Promise((resolve) => setTimeout(resolve, 500));
  assert.equal(await page.evaluate(() => window.admitted.length), count);
  assert.ok(count <= 2);
  await page.click('#pause');
  await page.waitForFunction(() => window.controller.getSnapshot().phase === 'completed', undefined, { timeout: 45000 });
  assert.deepEqual(await page.evaluate(() => window.admitted), [0, 1, 2]);
  await page.click('#start');
  await page.waitForFunction(() => window.controller.getSnapshot().phase === 'playing', undefined, { timeout: 30000 });
  const before = Date.now(); await page.click('#stop');
  assert.equal(await page.evaluate(() => window.controller.getSnapshot().phase), 'stopped');
  const localStopMs = Date.now() - before;
  await page.waitForFunction(() => window.controller.getSnapshot().cancellation === 'confirmed', undefined, { timeout: 30000 });
  console.log(JSON.stringify({ result: 'passed', real_model: true, output: 'muted Chromium', segments: 3, local_stop_observed_ms: localStopMs, server_cancel_observed_ms: Date.now() - before }));
} finally { await browser?.close(); await server.close(); }
