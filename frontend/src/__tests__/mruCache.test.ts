import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearAllComposerMruCaches, MRUCache } from '@/lib/mruCache';

const memoryStorage = (): Storage => {
  const data = new Map<string, string>();
  return {
    get length() { return data.size; },
    clear: () => data.clear(),
    getItem: (k) => (data.has(k) ? data.get(k)! : null),
    setItem: (k, v) => { data.set(k, String(v)); },
    removeItem: (k) => { data.delete(k); },
    key: (i) => Array.from(data.keys())[i] ?? null,
  };
};

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MRUCache', () => {
  it('returns empty list initially', () => {
    const cache = new MRUCache('test');
    expect(cache.load()).toEqual([]);
  });

  it('prepends recorded uses', () => {
    const cache = new MRUCache('test');
    cache.recordUse('a');
    cache.recordUse('b');
    cache.recordUse('c');
    expect(cache.load()).toEqual(['c', 'b', 'a']);
  });

  it('moves repeated key to front without dup', () => {
    const cache = new MRUCache('test');
    cache.recordUse('a');
    cache.recordUse('b');
    cache.recordUse('a');
    expect(cache.load()).toEqual(['a', 'b']);
  });

  it('respects limit', () => {
    const cache = new MRUCache('test', 3);
    cache.recordUse('a');
    cache.recordUse('b');
    cache.recordUse('c');
    cache.recordUse('d');
    expect(cache.load()).toEqual(['d', 'c', 'b']);
  });

  it('persists across instances', () => {
    const a = new MRUCache('persist-test');
    a.recordUse('foo');
    const b = new MRUCache('persist-test');
    expect(b.load()).toEqual(['foo']);
  });

  it('recencyRank ranks more recent higher', () => {
    const cache = new MRUCache('test');
    cache.recordUse('a');
    cache.recordUse('b');
    expect(cache.recencyRank('b')).toBeGreaterThan(cache.recencyRank('a'));
  });

  it('recencyRank returns 0 for unknown key', () => {
    const cache = new MRUCache('test');
    cache.recordUse('a');
    expect(cache.recencyRank('zzz')).toBe(0);
  });

  it('clear empties storage', () => {
    const cache = new MRUCache('test');
    cache.recordUse('a');
    cache.clear();
    expect(cache.load()).toEqual([]);
  });

  it('namespaces are isolated', () => {
    const a = new MRUCache('ns1');
    const b = new MRUCache('ns2');
    a.recordUse('foo');
    expect(b.load()).toEqual([]);
  });

  it('clears every composer namespace from storage and memory', () => {
    const commands = new MRUCache('commands');
    const mentions = new MRUCache('mentions');
    commands.recordUse('summarize');
    mentions.recordUse('filesystem|file:///private/report.txt');

    expect(clearAllComposerMruCaches()).toBe(true);

    expect(commands.load()).toEqual([]);
    expect(mentions.load()).toEqual([]);
    expect(localStorage.getItem('magi.composer.mru.commands')).toBeNull();
    expect(localStorage.getItem('magi.composer.mru.mentions')).toBeNull();
  });

  it('reports when browser storage refuses to remove composer content', () => {
    const stubbornStorage = memoryStorage();
    stubbornStorage.setItem('magi.composer.mru.mentions', '["private"]');
    stubbornStorage.removeItem = vi.fn();
    vi.stubGlobal('localStorage', stubbornStorage);

    expect(clearAllComposerMruCaches()).toBe(false);
    expect(localStorage.getItem('magi.composer.mru.mentions')).toBe('["private"]');
  });
});
