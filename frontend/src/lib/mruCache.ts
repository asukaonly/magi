/**
 * Most-recently-used cache backed by `localStorage`.
 *
 * Tracks an ordered list of arbitrary string keys per namespace. Used by
 * the @-picker (recent MCP resource URIs) and /-picker (recent command
 * names) to surface frequently used items first.
 *
 * The list is bounded to `limit` entries; ties at the same fuzzy-match
 * score are broken by recency.
 */

const PREFIX = 'magi.composer.mru.';
let cacheGeneration = 0;

const safeStorage = (): Storage | null => {
  try {
    if (typeof window === 'undefined') return null;
    const ls = window.localStorage;
    // Probe — Safari private mode throws on writes.
    ls.setItem(`${PREFIX}__probe`, '1');
    ls.removeItem(`${PREFIX}__probe`);
    return ls;
  } catch {
    return null;
  }
};

export class MRUCache {
  private namespace: string;
  private limit: number;
  private cache: string[] | null = null;
  private generation = cacheGeneration;

  constructor(namespace: string, limit = 20) {
    this.namespace = namespace;
    this.limit = limit;
  }

  private storageKey(): string {
    return `${PREFIX}${this.namespace}`;
  }

  load(): string[] {
    if (this.generation !== cacheGeneration) {
      this.cache = null;
      this.generation = cacheGeneration;
    }
    if (this.cache !== null) return this.cache;
    const ls = safeStorage();
    if (!ls) {
      this.cache = [];
      return this.cache;
    }
    try {
      const raw = ls.getItem(this.storageKey());
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      if (
        Array.isArray(parsed) &&
        parsed.every((item) => typeof item === 'string')
      ) {
        this.cache = parsed.slice(0, this.limit);
        return this.cache;
      }
    } catch {
      // fall through to empty
    }
    this.cache = [];
    return this.cache;
  }

  recordUse(key: string): void {
    if (!key) return;
    const current = this.load().filter((entry) => entry !== key);
    current.unshift(key);
    if (current.length > this.limit) current.length = this.limit;
    this.cache = current;
    const ls = safeStorage();
    if (!ls) return;
    try {
      ls.setItem(this.storageKey(), JSON.stringify(current));
    } catch {
      // ignore quota / disabled storage
    }
  }

  /**
   * Return a recency rank for ``key``: higher = more recent.
   * Returns 0 if key isn't in the MRU list.
   */
  recencyRank(key: string): number {
    const list = this.load();
    const idx = list.indexOf(key);
    if (idx < 0) return 0;
    return list.length - idx;
  }

  clear(): void {
    this.cache = [];
    this.generation = cacheGeneration;
    const ls = safeStorage();
    if (!ls) return;
    try {
      ls.removeItem(this.storageKey());
    } catch {
      // ignore
    }
  }
}

export function clearAllComposerMruCaches(): boolean {
  cacheGeneration += 1;
  const storage = safeStorage();
  if (!storage) {
    return typeof window === 'undefined';
  }
  try {
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(PREFIX)) {
        keys.push(key);
      }
    }
    for (const key of keys) {
      storage.removeItem(key);
    }
    for (let index = 0; index < storage.length; index += 1) {
      if (storage.key(index)?.startsWith(PREFIX)) {
        return false;
      }
    }
    return true;
  } catch {
    return false;
  }
}
