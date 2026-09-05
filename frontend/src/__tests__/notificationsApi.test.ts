import { describe, expect, it, vi, beforeEach } from 'vitest';
import { api } from '@/api/client';
import * as notif from '@/api/modules/notifications';

describe('notifications api', () => {
  beforeEach(() => vi.restoreAllMocks());
  it('listNotifications unwraps the gateway envelope', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ success: true, data: { items: [{ id: 1 }], unread_count: 1, total: 26 } } as any);
    const r = await notif.listNotifications();
    expect(api.get).toHaveBeenCalledWith('/notifications', { params: undefined });
    expect(r.unread_count).toBe(1);
    expect(r.total).toBe(26);
  });
  it('forwards pending conflict pagination before unwrapping', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ success: true, data: { items: [], unread_count: 0, total: 26 } });
    const params = { limit: 25, offset: 25, profile_conflicts_only: true };
    const result = await notif.listNotifications(params);
    expect(api.get).toHaveBeenCalledWith('/notifications', { params });
    expect(result.total).toBe(26);
  });
  it('markAllRead posts {all:true}', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, data: {} } as any);
    await notif.markAllRead();
    expect(post).toHaveBeenCalledWith('/notifications/mark-read', { all: true });
  });
  it('actionNotification posts to the id path', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ success: true, data: {} } as any);
    await notif.actionNotification(7);
    expect(post).toHaveBeenCalledWith('/notifications/7/action', {});
  });
});
