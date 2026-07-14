import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import * as api from '@/api/modules/notifications';
import { useNotifications } from '@/hooks/useNotifications';

describe('useNotifications', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'listNotifications').mockResolvedValue({
      items: [{ id: 1, kind: 'suggestion', dedupe_key: 'browser_history', title: 't', body: 'b',
        payload: { plugins: [] }, status: 'unread', created_at_ms: 1, read_at_ms: null }],
      unread_count: 1,
    });
    vi.spyOn(api, 'markRead').mockResolvedValue();
    vi.spyOn(api, 'markAllRead').mockResolvedValue();
  });
  it('hydrates items + unreadCount', async () => {
    const { result } = renderHook(() => useNotifications());
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(result.current.unreadCount).toBe(1);
  });
  it('markRead calls api then refreshes', async () => {
    const { result } = renderHook(() => useNotifications());
    await waitFor(() => expect(result.current.items.length).toBe(1));
    await act(async () => { await result.current.markRead([1]); });
    expect(api.markRead).toHaveBeenCalledWith([1]);
  });
});
