import { useEffect } from 'react';
import { useNotificationStore } from '@/stores/notifications';

export function useNotifications() {
  const store = useNotificationStore();
  const refresh = store.refresh;
  useEffect(() => { void refresh(); }, [refresh]);  // hydrate on mount
  return store;
}
