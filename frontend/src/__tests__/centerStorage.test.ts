import { beforeEach, describe, expect, it } from 'vitest';
import { centerLocalStorage, centerSessionStorage, setCenterStorageScope } from '@/runtime/center-storage';
describe('center cache ownership', () => {
  beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); });
  it('isolates matching item identities across centers and preserves device preferences', () => {
    window.localStorage.setItem('magi_language', 'zh-CN');
    setCenterStorageScope('a', 'epoch-1'); centerLocalStorage().setItem('session', 'A');
    const captured = centerLocalStorage();
    setCenterStorageScope('b', 'epoch-1'); expect(centerLocalStorage().getItem('session')).toBeNull();
    centerLocalStorage().setItem('session', 'B'); captured.setItem('late', 'still A');
    expect(centerLocalStorage().getItem('late')).toBeNull();
    setCenterStorageScope('a', 'epoch-1'); expect(centerLocalStorage().getItem('session')).toBe('A');
    expect(window.localStorage.getItem('magi_language')).toBe('zh-CN');
  });
  it('removes offline content from an obsolete data epoch before it can be read', () => {
    setCenterStorageScope('a', 'old'); centerLocalStorage().setItem('draft', 'private'); centerSessionStorage().setItem('retry', 'private');
    setCenterStorageScope('b', 'old'); centerLocalStorage().setItem('draft', 'keep');
    setCenterStorageScope('a', 'new');
    expect(centerLocalStorage().getItem('draft')).toBeNull(); expect(centerSessionStorage().length).toBe(0);
    expect([...Array(window.localStorage.length).keys()].map((i) => window.localStorage.key(i)).some((key) => key?.startsWith('magi.center.a.old.'))).toBe(false);
    setCenterStorageScope('b', 'old'); expect(centerLocalStorage().getItem('draft')).toBe('keep');
  });
});
