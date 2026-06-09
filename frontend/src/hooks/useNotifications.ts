import { useEffect } from 'react';
import { useNotificationStore } from '@/stores/notifications';

export function useNotifications() {
  const store = useNotificationStore();
  useEffect(() => { void store.refresh(); }, []);  // hydrate on mount
  return store;
}
