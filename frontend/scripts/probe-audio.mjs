// Optional browser integration probe. Requires Playwright and a Chromium browser.
// Usage: node scripts/probe-audio.mjs [playwright-package-path] [browser-channel]
/* global window, document */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const { chromium } = createRequire(import.meta.url)(process.argv[2] || 'playwright');
const server = await createServer({
  configFile: false,
  logLevel: 'error',
  root: fileURLToPath(new URL('..', import.meta.url)),
  optimizeDeps: { noDiscovery: true, entries: [] },
  server: { host: '127.0.0.1', port: 5188, hmr: false },
});
let browser;
try {
  await server.listen();
  browser = await chromium.launch({
    ...(process.argv[3] ? { channel: process.argv[3] } : {}),
    headless: true,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--mute-audio'],
  });
  const page = await browser.newPage();
  await page.route('**/audio-probe', (route) => route.fulfill({
    contentType: 'text/html', body: '<button id="start">Start test</button>',
  }));
  await page.goto(`${server.resolvedUrls.local[0]}audio-probe`);
  const resampling = await page.evaluate(async () => {
    const { normalizeRecording, inspectWav } = await import('/src/lib/audio/format.ts');
    const results = [];
    for (const rate of [44100, 48000, 96000]) {
      for (const hz of [1000, 12000]) {
        const samples = Float32Array.from({ length: rate }, (_, i) => 0.8 * Math.sin(2 * Math.PI * hz * i / rate));
        const wav = await normalizeRecording(samples, rate);
        const view = new DataView(wav);
        let power = 0;
        let sine = 0;
        let cosine = 0;
        for (let i = 100; i < 15900; i += 1) {
          const value = view.getInt16(44 + i * 2, true) / 32768;
          power += value * value;
          sine += value * Math.sin(2 * Math.PI * hz * i / 16000);
          cosine += value * Math.cos(2 * Math.PI * hz * i / 16000);
        }
        results.push({ rate, hz, ...inspectWav(wav), rms: Math.sqrt(power / 15800), amplitude: 2 * Math.hypot(sine, cosine) / 15800 });
      }
    }
    return results;
  });
  for (const result of resampling) {
    assert.equal(result.frames, 16000);
    assert.equal(result.sampleRate, 16000);
    assert.equal(result.channels, 1);
    if (result.hz === 1000) assert.ok(Math.abs(result.amplitude - 0.8) < 0.01, JSON.stringify(result));
    else assert.ok(result.rms < 0.02, JSON.stringify(result));
  }
  await page.evaluate(async () => {
    const { WavRecorder } = await import('/src/lib/audio/recorder.ts');
    const { SegmentAudioPlayer } = await import('/src/lib/audio/player.ts');
    window.recorder = new WavRecorder();
    window.player = new SegmentAudioPlayer();
    document.querySelector('#start').onclick = () => { void window.recorder.start(); };
  });
  await page.click('#start');
  await page.waitForFunction(() => window.recorder.getSnapshot().phase === 'recording');
  await page.waitForTimeout(1200);
  const recording = await page.evaluate(async () => {
    await window.recorder.stop();
    const state = window.recorder.getSnapshot();
    const { inspectWav } = await import('/src/lib/audio/format.ts');
    return { phase: state.phase, seconds: state.seconds, ...inspectWav(state.audio), bytes: state.audio.byteLength };
  });
  assert.equal(recording.phase, 'ready');
  assert.ok(recording.frames >= 16000);
  assert.equal(recording.sampleRate, 16000);
  await page.evaluate(() => {
    document.querySelector('#start').onclick = async () => {
      const session = await window.player.begin();
      await window.player.enqueue(session, 0, window.recorder.getSnapshot().audio);
      window.player.finish(session);
    };
  });
  await page.click('#start');
  await page.waitForFunction(() => window.player.getSnapshot().phase === 'playing');
  const playback = await page.evaluate(async () => {
    await window.player.setPaused(true);
    const paused = window.player.getSnapshot().phase;
    await window.player.setPaused(false);
    const resumed = window.player.getSnapshot().phase;
    window.player.stop();
    window.recorder.cancel();
    return { paused, resumed, stopped: window.player.getSnapshot().phase };
  });
  assert.deepEqual(playback, { paused: 'paused', resumed: 'playing', stopped: 'stopped' });
  console.log(JSON.stringify({ browser: await browser.version(), resampling, recording, playback }, null, 2));
} finally {
  await browser?.close();
  await server.close();
}
