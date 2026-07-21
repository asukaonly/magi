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

  it('defaults new users to apricot mode resolved as light', async () => {
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

    expect(state.mode).toBe('apricot');
    expect(state.resolvedTheme).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-apricot')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it.each(['matcha', 'persimmon', 'apricot'] as const)(
    'applies the %s palette class from stored theme mode',
    async (mode) => {
      vi.stubGlobal(
        'localStorage',
        {
          getItem: vi.fn(() => mode),
          setItem: vi.fn(),
        }
      );
      vi.stubGlobal('matchMedia', createMatchMedia(false));

      const { useThemeStore } = await import('@/stores/theme');
      const state = useThemeStore.getState();

      expect(state.mode).toBe(mode);
      expect(state.resolvedTheme).toBe('light');
      expect(document.documentElement.classList.contains('light')).toBe(true);
      expect(document.documentElement.classList.contains(`theme-${mode}`)).toBe(true);
      expect(document.documentElement.classList.contains('dark')).toBe(false);
    },
  );

  it('applies the soft mist palette class from stored theme mode', async () => {
    vi.stubGlobal(
      'localStorage',
      {
        getItem: vi.fn(() => 'mist'),
        setItem: vi.fn(),
      }
    );
    vi.stubGlobal('matchMedia', createMatchMedia(false));

    const { useThemeStore } = await import('@/stores/theme');
    const state = useThemeStore.getState();

    expect(state.mode).toBe('mist');
    expect(state.resolvedTheme).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(document.documentElement.classList.contains('theme-mist')).toBe(true);
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });
});
