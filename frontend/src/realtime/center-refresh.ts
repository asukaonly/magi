import { APP_EVENTS } from '@/constants/events';

const listeners = new Set<() => void>();
let timer: number | null = null;
let interval: number | null = null;
let lastRefreshAt = 0;
let maintenance = false;

function schedule(): void {
  if (timer !== null || document.visibilityState === 'hidden' || maintenance) return;
  timer = window.setTimeout(() => {
    timer = null;
    if (document.visibilityState === 'hidden' || maintenance) return;
    lastRefreshAt = Date.now();
    for (const listener of listeners) listener();
  }, Math.max(250, 2_000 - (Date.now() - lastRefreshAt)));
}

function onMaintenance(event: Event): void {
  const detail: unknown = event instanceof CustomEvent ? event.detail : null;
  if (!detail || typeof detail !== 'object' || !('status' in detail)) return;
  maintenance = detail.status !== 'idle';
  if (!maintenance) schedule();
}

/** One bounded invalidation clock for mounted views; events are hints, never write commands. */
export function subscribeCenterRefresh(listener: () => void): () => void {
  if (listeners.size === 0) {
    lastRefreshAt = 0;
    window.addEventListener(APP_EVENTS.CENTER_STATE_CHANGED, schedule);
    window.addEventListener(APP_EVENTS.CENTER_MAINTENANCE, onMaintenance);
    window.addEventListener('focus', schedule);
    window.addEventListener('online', schedule);
    document.addEventListener('visibilitychange', schedule);
    interval = window.setInterval(schedule, 30_000);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size) return;
    window.removeEventListener(APP_EVENTS.CENTER_STATE_CHANGED, schedule);
    window.removeEventListener(APP_EVENTS.CENTER_MAINTENANCE, onMaintenance);
    window.removeEventListener('focus', schedule);
    window.removeEventListener('online', schedule);
    document.removeEventListener('visibilitychange', schedule);
    if (timer !== null) window.clearTimeout(timer);
    if (interval !== null) window.clearInterval(interval);
    timer = null; interval = null; maintenance = false;
  };
}
