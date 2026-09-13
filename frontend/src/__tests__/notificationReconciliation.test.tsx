import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { APP_EVENTS } from '@/constants/events';
import { useNotifications } from '@/hooks/useNotifications';
import * as api from '@/api/modules/notifications';

vi.mock('@/runtime/background-delivery', () => ({ readBackgroundDeliveryStatus: async () => null }));
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it('shares reconciliation across mounted consumers after another device reads a notification', async () => {
  vi.useFakeTimers();
  const list = vi.spyOn(api, 'listNotifications').mockResolvedValue({ items: [], unread_count: 3, total: 3 });
  const bell = renderHook(() => useNotifications());
  const panel = renderHook(() => useNotifications());
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(list).toHaveBeenCalledTimes(1);
  expect(bell.result.current.unreadCount).toBe(3);
  list.mockResolvedValue({ items: [], unread_count: 0, total: 3 });
  await act(async () => {
    window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED));
    window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    await vi.advanceTimersByTimeAsync(2_001);
  });
  expect(list).toHaveBeenCalledTimes(2);
  expect(bell.result.current.unreadCount).toBe(0);
  expect(panel.result.current.unreadCount).toBe(0);
  await act(async () => {
    window.dispatchEvent(new Event('focus'));
    await vi.advanceTimersByTimeAsync(2_001);
  });
  expect(list).toHaveBeenCalledTimes(3);
  bell.unmount(); panel.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(list).toHaveBeenCalledTimes(3);
});

it('performs one trailing read when a change arrives during a slow refresh', async () => {
  vi.useFakeTimers();
  let finish: (value: { items: []; unread_count: number; total: number }) => void = () => undefined;
  const list = vi.spyOn(api, 'listNotifications')
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
    .mockResolvedValue({ items: [], unread_count: 0, total: 0 });
  const view = renderHook(() => useNotifications());
  await act(async () => {
    window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED));
    await vi.advanceTimersByTimeAsync(2_001);
  });
  expect(list).toHaveBeenCalledTimes(1);
  await act(async () => { finish({ items: [], unread_count: 1, total: 1 }); });
  expect(list).toHaveBeenCalledTimes(2);
  expect(view.result.current.unreadCount).toBe(0);
  view.unmount();
});
