import { create } from 'zustand';
import { readBackgroundDeliveryStatus } from '@/runtime/background-delivery';
import { getRuntimeGeneration } from '@/runtime/config';
import {
  listNotifications, markRead as apiMarkRead, markAllRead as apiMarkAllRead,
  dismissNotification, dismissAllNotifications, actionNotification, type NotificationItem,
} from '@/api/modules/notifications';

let refreshRequestId = 0;

interface NotificationState {
  items: NotificationItem[];
  unreadCount: number;
  loading: boolean;
  readError: boolean;
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
  readError: false,
  refresh: async () => {
    const generation = getRuntimeGeneration();
    const requestId = refreshRequestId + 1;
    refreshRequestId = requestId;
    set({ loading: true });
    try {
      const [{ items, unread_count }, pending] = await Promise.all([
        listNotifications(), readBackgroundDeliveryStatus().catch(() => null),
      ]);
      if (requestId === refreshRequestId && generation === getRuntimeGeneration()) {
        const ids = new Set(pending?.notification_read_ids ?? []);
        const pendingUnread = items.filter((item) => item.status === 'unread' && ids.has(item.id)).length;
        set({ items: items.map((item) => item.status === 'unread' && ids.has(item.id) ? { ...item, status: 'read' } : item), unreadCount: Math.max(0, unread_count - pendingUnread) });
      }
    } catch {
      // keep last-known on failure
    } finally {
      if (requestId === refreshRequestId && generation === getRuntimeGeneration()) {
        set({ loading: false });
      }
    }
  },
  markRead: async (ids) => {
    const generation = getRuntimeGeneration();
    try {
      await apiMarkRead(ids);
      if (generation !== getRuntimeGeneration()) return;
      refreshRequestId += 1;
      set((state) => ({
        readError: false,
        items: state.items.map((item) => ids.includes(item.id) && item.status === 'unread' ? { ...item, status: 'read' } : item),
        unreadCount: Math.max(0, state.unreadCount - state.items.filter((item) => ids.includes(item.id) && item.status === 'unread').length),
      }));
    } catch {
      if (generation === getRuntimeGeneration()) set({ readError: true });
    }
  },
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
    set({ items: [], unreadCount: 0, loading: false, readError: false });
  },
}));
