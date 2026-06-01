import { create } from 'zustand';
import {
  listNotifications, markRead as apiMarkRead, markAllRead as apiMarkAllRead,
  dismissNotification, dismissAllNotifications, actionNotification, type NotificationItem,
} from '@/api/modules/notifications';

interface NotificationState {
  items: NotificationItem[];
  unreadCount: number;
  loading: boolean;
  refresh: () => Promise<void>;
  markRead: (ids: number[]) => Promise<void>;
  markAllRead: () => Promise<void>;
  dismiss: (id: number) => Promise<void>;
  dismissAll: () => Promise<void>;
  act: (id: number) => Promise<void>;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  items: [],
  unreadCount: 0,
  loading: false,
  refresh: async () => {
    set({ loading: true });
    try {
      const { items, unread_count } = await listNotifications();
      set({ items, unreadCount: unread_count });
    } catch {
      // keep last-known on failure
    } finally {
      set({ loading: false });
    }
  },
  markRead: async (ids) => { await apiMarkRead(ids); await get().refresh(); },
  markAllRead: async () => { await apiMarkAllRead(); await get().refresh(); },
  dismiss: async (id) => { await dismissNotification(id); await get().refresh(); },
  dismissAll: async () => { await dismissAllNotifications(); await get().refresh(); },
  act: async (id) => { await actionNotification(id); await get().refresh(); },
}));
