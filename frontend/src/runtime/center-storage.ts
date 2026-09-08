/** Browser content caches belong to a center and its current content epoch. */
let prefix = 'magi.center.unbound.';
const UNSCOPED_CONTENT_KEYS = new Set([
  'magi_onboarding_state', 'magi.chat.retryable-sends', 'magi.chat.inline-skill-retries',
  'magi.chat.readCursors.v1', 'magi.chat.readCursors.initialized.v1',
  'magi.desktopNotifications.sent.v1', 'magi_memory_portability_operation_v1',
]);
const UNSCOPED_CONTENT_PREFIXES = ['chat_session_', 'magi.composer.mru.', 'magi.first-context-continuation:'];

class CenterStorage implements Storage {
  constructor(private readonly storage: Storage, private readonly prefix: string) {}
  private keys(): string[] {
    const keys: string[] = [];
    for (let index = 0; index < this.storage.length; index += 1) {
      const key = this.storage.key(index);
      if (key?.startsWith(this.prefix)) keys.push(key.slice(this.prefix.length));
    }
    return keys;
  }
  get length(): number { return this.keys().length; }
  key(index: number): string | null { return this.keys()[index] ?? null; }
  getItem(key: string): string | null { return this.storage.getItem(this.prefix + key); }
  setItem(key: string, value: string): void { this.storage.setItem(this.prefix + key, value); }
  removeItem(key: string): void { this.storage.removeItem(this.prefix + key); }
  clear(): void { this.keys().forEach((key) => this.removeItem(key)); }
}

export function centerStorageKey(key: string): string { return prefix + key; }
export function centerLocalStorage(): Storage { return new CenterStorage(window.localStorage, prefix); }
export function centerSessionStorage(): Storage { return new CenterStorage(window.sessionStorage, prefix); }

export function setCenterStorageScope(serverId: string, contentEpoch: string): void {
  if (!serverId || !contentEpoch) throw new Error('Center storage identity is missing');
  const serverPrefix = `magi.center.${encodeURIComponent(serverId)}.`;
  const nextPrefix = `${serverPrefix}${encodeURIComponent(contentEpoch)}.`;
  let changed = false;
  // Offline devices learn about clears before loading any cached content.
  for (const storage of [window.localStorage, window.sessionStorage]) {
    const obsolete: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key && ((key.startsWith(serverPrefix) && !key.startsWith(nextPrefix))
        || UNSCOPED_CONTENT_KEYS.has(key) || UNSCOPED_CONTENT_PREFIXES.some((value) => key.startsWith(value)))) obsolete.push(key);
    }
    obsolete.forEach((key) => storage.removeItem(key));
    changed ||= obsolete.length > 0;
    if (obsolete.some((key) => storage.getItem(key) !== null)) throw new Error('Obsolete center cache could not be cleared');
  }
  prefix = nextPrefix;
  if (changed) centerLocalStorage().setItem('maintenance.device-cleanup', 'pending');
}
