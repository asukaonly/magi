import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

async function processor() {
  const port = { onmessage: null as ((event: { data: unknown }) => void) | null, postMessage: vi.fn() };
  let Processor!: new () => { process(inputs: Float32Array[][]): boolean };
  vi.stubGlobal('sampleRate', 8000);
  vi.stubGlobal('AudioWorkletProcessor', class { port = port; });
  vi.stubGlobal('registerProcessor', (_name: string, implementation: typeof Processor) => { Processor = implementation; });
  await import('../capture.worklet');
  return { node: new Processor(), port };
}

it('mixes channels and flushes the final partial block exactly once', async () => {
  const { node, port } = await processor();
  node.process([[new Float32Array([1, 0.5]), new Float32Array([-1, 0.5])]]);
  port.onmessage?.({ data: 'stop' });
  expect(port.postMessage.mock.calls[0][0]).toEqual(new Float32Array([0, 0.5]));
  expect(port.postMessage.mock.calls[1][0]).toBe('stopped');
  expect(node.process([[new Float32Array([1])]])).toBe(false);
  expect(port.postMessage).toHaveBeenCalledTimes(2);
});

it('stops at 60 seconds even when main-thread timers cannot run', async () => {
  const { node, port } = await processor();
  expect(node.process([[new Float32Array(8000 * 60 + 100)]])).toBe(false);
  const chunks = port.postMessage.mock.calls.map(([data]) => data).filter((data) => data instanceof Float32Array);
  expect(chunks.reduce((total, chunk) => total + chunk.length, 0)).toBe(8000 * 60);
  expect(port.postMessage.mock.calls.slice(-1)[0]?.[0]).toBe('stopped');
});
