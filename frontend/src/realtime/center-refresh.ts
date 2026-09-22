import { APP_EVENTS } from '@/constants/events';

type Subscription = { listener: () => void; resources: ReadonlySet<string> };
const listeners = new Set<Subscription>();
let timer: number | null = null;
let interval: number | null = null;
let lastRefreshAt = 0;
let maintenance = false;
let refreshAll = false;
const pendingResources = new Set<string>();

function schedule(resources?: readonly string[]): void {
  if (document.visibilityState === 'hidden' || maintenance) return;
  if (resources) resources.forEach((resource) => pendingResources.add(resource));
  else refreshAll = true;
  if (timer !== null) return;
  timer = window.setTimeout(() => {
    timer = null;
    if (document.visibilityState === 'hidden' || maintenance) return;
    const all = refreshAll;
    const changed = new Set(pendingResources);
    refreshAll = false;
    pendingResources.clear();
    lastRefreshAt = Date.now();
    for (const { listener, resources: scope } of listeners) {
      if (all || [...changed].some((resource) => scope.has(resource))) listener();
    }
  }, Math.max(250, 2_000 - (Date.now() - lastRefreshAt)));
}

function onStateChanged(event: Event): void {
  const detail: unknown = event instanceof CustomEvent ? event.detail : null;
  if (detail && typeof detail === 'object' && 'resource' in detail && typeof detail.resource === 'string') {
    schedule([detail.resource]);
  } else schedule();
}
const reconcileAll = () => schedule();
const reconcileSessions = () => schedule(['chat', 'messages', 'sessions', 'control']);

function onMaintenance(event: Event): void {
  const detail: unknown = event instanceof CustomEvent ? event.detail : null;
  if (!detail || typeof detail !== 'object' || !('status' in detail)) return;
  maintenance = detail.status !== 'idle';
  if (!maintenance) schedule();
}

/** Resource hints refresh affected views; focus and the fallback clock reconcile all snapshots. */
export function subscribeCenterRefresh(listener: () => void, resources: readonly string[]): () => void {
  if (listeners.size === 0) {
    lastRefreshAt = 0;
    window.addEventListener(APP_EVENTS.CENTER_STATE_CHANGED, onStateChanged);
    window.addEventListener(APP_EVENTS.SESSION_SYNC, reconcileSessions);
    window.addEventListener(APP_EVENTS.CENTER_MAINTENANCE, onMaintenance);
    window.addEventListener('focus', reconcileAll);
    window.addEventListener('online', reconcileAll);
    document.addEventListener('visibilitychange', reconcileAll);
    interval = window.setInterval(reconcileAll, 30_000);
  }
  const subscription = { listener, resources: new Set(resources) };
  listeners.add(subscription);
  return () => {
    listeners.delete(subscription);
    if (listeners.size) return;
    window.removeEventListener(APP_EVENTS.CENTER_STATE_CHANGED, onStateChanged);
    window.removeEventListener(APP_EVENTS.SESSION_SYNC, reconcileSessions);
    window.removeEventListener(APP_EVENTS.CENTER_MAINTENANCE, onMaintenance);
    window.removeEventListener('focus', reconcileAll);
    window.removeEventListener('online', reconcileAll);
    document.removeEventListener('visibilitychange', reconcileAll);
    if (timer !== null) window.clearTimeout(timer);
    if (interval !== null) window.clearInterval(interval);
    timer = null; interval = null; maintenance = false; refreshAll = false;
    pendingResources.clear();
  };
}
