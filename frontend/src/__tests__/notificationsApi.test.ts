import { describe, expect, it, vi, beforeEach } from 'vitest';
import { api } from '@/api/client';
import * as notif from '@/api/modules/notifications';

describe('notifications api', () => {
  beforeEach(() => vi.restoreAllMocks());
  it('listNotifications unwraps the gateway envelope', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ success: true, data: { items: [{ id: 1 }], unread_count: 1 } } as any);
    const r = await notif.listNotifications();
    expect(api.get).toHaveBeenCalledWith('/notifications');
    expect(r.unread_count).toBe(1);
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
