import { create } from 'zustand';
import {
  listNotifications, markRead as apiMarkRead, markAllRead as apiMarkAllRead,
  dismissNotification, dismissAllNotifications, actionNotification, type NotificationItem,
} from '@/api/modules/notifications';

let refreshRequestId = 0;

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
  discardMemoryConflicts: () => void;
  clearForMemoryClear: () => void;
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  items: [],
  unreadCount: 0,
  loading: false,
  refresh: async () => {
    const requestId = refreshRequestId + 1;
    refreshRequestId = requestId;
    set({ loading: true });
    try {
      const { items, unread_count } = await listNotifications();
      if (requestId === refreshRequestId) {
        set({ items, unreadCount: unread_count });
      }
    } catch {
      // keep last-known on failure
    } finally {
      if (requestId === refreshRequestId) {
        set({ loading: false });
      }
    }
  },
  markRead: async (ids) => { await apiMarkRead(ids); await get().refresh(); },
  markAllRead: async () => { await apiMarkAllRead(); await get().refresh(); },
  dismiss: async (id) => { await dismissNotification(id); await get().refresh(); },
  dismissAll: async () => { await dismissAllNotifications(); await get().refresh(); },
  act: async (id) => { await actionNotification(id); await get().refresh(); },
  discardMemoryConflicts: () => {
    refreshRequestId += 1;
    set((state) => {
      const removedUnreadCount = state.items.filter(
        (item) => (
          (
            item.payload?.conflict_type === 'profile_conflict'
            || item.dedupe_key.startsWith('profile_conflict:')
          )
          && item.status === 'unread'
        ),
      ).length;
      const items = state.items.filter(
        (item) => (
          item.payload?.conflict_type !== 'profile_conflict'
          && !item.dedupe_key.startsWith('profile_conflict:')
        ),
      );
      return {
        items,
        unreadCount: Math.max(0, state.unreadCount - removedUnreadCount),
        loading: false,
      };
    });
  },
  clearForMemoryClear: () => {
    refreshRequestId += 1;
    set({ items: [], unreadCount: 0, loading: false });
  },
}));
