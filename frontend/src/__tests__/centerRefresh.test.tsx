import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { APP_EVENTS } from '@/constants/events';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });
const hint = () => window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED));

it('coalesces hints and serializes reconciliation with one trailing read', async () => {
  let finish: (() => void) | undefined;
  const refresh = vi.fn().mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; })).mockResolvedValue(undefined);
  const view = renderHook(() => useCenterRefresh(refresh));
  await act(async () => { hint(); hint(); await vi.advanceTimersByTimeAsync(250); });
  expect(refresh).toHaveBeenCalledTimes(1);
  await act(async () => { hint(); await vi.advanceTimersByTimeAsync(2_000); hint(); await vi.advanceTimersByTimeAsync(2_000); });
  expect(refresh).toHaveBeenCalledTimes(1);
  await act(async () => { finish?.(); });
  expect(refresh).toHaveBeenCalledTimes(2);
  view.unmount();
  await act(async () => { hint(); await vi.advanceTimersByTimeAsync(31_000); });
  expect(refresh).toHaveBeenCalledTimes(2);
});

it('reconciles after focus and periodically even if a hint was lost', async () => {
  const refresh = vi.fn();
  const view = renderHook(() => useCenterRefresh(refresh));
  await act(async () => { window.dispatchEvent(new Event('focus')); await vi.advanceTimersByTimeAsync(250); });
  expect(refresh).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  expect(refresh).toHaveBeenCalledTimes(2);
  view.unmount();
});

it('holds reads during maintenance and resumes when the center is ready', async () => {
  const refresh = vi.fn();
  const view = renderHook(() => useCenterRefresh(refresh));
  await act(async () => {
    window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_MAINTENANCE, { detail: { status: 'running' } }));
    hint(); await vi.advanceTimersByTimeAsync(31_000);
  });
  expect(refresh).not.toHaveBeenCalled();
  await act(async () => {
    window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_MAINTENANCE, { detail: { status: 'idle' } }));
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(refresh).toHaveBeenCalledTimes(1);
  view.unmount();
});
