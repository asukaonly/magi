import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStreamingText } from '@/hooks/useStreamingText';

// Drive rAF via a controllable shim so tests are deterministic.
type RafCallback = (ts: number) => void;

let now = 0;
let pendingRafs: RafCallback[] = [];

function flushFrame(deltaMs: number) {
  now += deltaMs;
  const callbacks = pendingRafs;
  pendingRafs = [];
  for (const cb of callbacks) {
    cb(now);
  }
}

beforeEach(() => {
  now = 0;
  pendingRafs = [];
  vi.stubGlobal('requestAnimationFrame', (cb: RafCallback) => {
    pendingRafs.push(cb);
    return pendingRafs.length;
  });
  vi.stubGlobal('cancelAnimationFrame', (_id: number) => {
    // No-op for the shim — flushFrame() drains everything queued.
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('useStreamingText', () => {
  it('passes through target when not streaming', () => {
    const { result } = renderHook(() => useStreamingText('hello world', false));
    expect(result.current).toBe('hello world');
  });

  it('passes through target when disabled (reduced motion)', () => {
    const { result } = renderHook(() =>
      useStreamingText('hello world', true, { disabled: true }),
    );
    expect(result.current).toBe('hello world');
  });

  it('reveals text gradually while streaming', () => {
    const { result, rerender } = renderHook(
      ({ t, s }) => useStreamingText(t, s),
      { initialProps: { t: '', s: true } },
    );
    // Target jumps to 1000 chars; drip should NOT snap to the end.
    rerender({ t: 'x'.repeat(1000), s: true });
    expect(result.current.length).toBe(0);

    // First frame: ~16ms — should reveal some but nowhere near 1000.
    act(() => flushFrame(16));
    expect(result.current.length).toBeGreaterThan(0);
    expect(result.current.length).toBeLessThan(1000);
  });

  it('snaps to full target when streaming ends', () => {
    const { result, rerender } = renderHook(
      ({ t, s }) => useStreamingText(t, s),
      { initialProps: { t: 'short reply', s: true } },
    );
    // Partial reveal then flip isStreaming=false → snap.
    act(() => flushFrame(16));
    rerender({ t: 'short reply', s: false });
    expect(result.current).toBe('short reply');
  });

  it('snaps when target shrinks (retract / revision safety)', () => {
    const { result, rerender } = renderHook(
      ({ t, s }) => useStreamingText(t, s),
      { initialProps: { t: 'this is a long initial reply', s: true } },
    );
    // Reveal enough that rendered.length > new target.length.
    act(() => flushFrame(200));   // ~12 chars at 60cps
    const revealedLen = result.current.length;
    expect(revealedLen).toBeGreaterThan(0);

    // Target shrinks (producer retracted or revised down).
    rerender({ t: 'short', s: true });
    expect(result.current).toBe('short');
  });

  it('respects min rate for tiny backlogs', () => {
    const { result, rerender } = renderHook(
      ({ t, s }) => useStreamingText(t, s, { minCharsPerSecond: 60 }),
      { initialProps: { t: '', s: true } },
    );
    // 10-char target → backlog tiny → use floor rate.
    rerender({ t: '0123456789', s: true });
    // After 50ms at 60cps the floor would reveal floor(60 * 0.05) = 3 chars
    // (but max(1, ...) clamp means at least 1).
    act(() => flushFrame(50));
    expect(result.current.length).toBeGreaterThanOrEqual(1);
    expect(result.current.length).toBeLessThanOrEqual(5);
  });

  it('speeds up on large backlogs (adaptive ceiling)', () => {
    const { result, rerender } = renderHook(
      ({ t, s }) =>
        useStreamingText(t, s, { minCharsPerSecond: 60, maxCharsPerSecond: 240 }),
      { initialProps: { t: '', s: true } },
    );
    rerender({ t: 'x'.repeat(5000), s: true });
    // After 100ms, adaptive rate maxes at 240cps → reveal ~24 chars (much
    // more than the 6 the floor would give us).
    act(() => flushFrame(100));
    expect(result.current.length).toBeGreaterThan(10);
  });
});
