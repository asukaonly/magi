import { afterEach, describe, expect, it, vi } from 'vitest';

const createMatchMedia = (matches: boolean) =>
  vi.fn().mockImplementation(() => ({
    matches,
    media: '(prefers-color-scheme: dark)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));

describe('theme store initialization', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    document.documentElement.className = '';
  });

  it('defaults to system mode and resolves to light when system preference is light', async () => {
    vi.stubGlobal(
      'localStorage',
      {
        getItem: vi.fn(() => null),
        setItem: vi.fn(),
      }
    );
    vi.stubGlobal('matchMedia', createMatchMedia(false));

    const { useThemeStore } = await import('@/stores/theme');
    const state = useThemeStore.getState();

    expect(state.mode).toBe('system');
    expect(state.resolvedTheme).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});
