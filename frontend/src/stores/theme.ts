import { create } from 'zustand';

export const THEME_MODE_OPTIONS = [
  'light',
  'dark',
  'system',
  'warm-neutral',
  'cool-studio',
  'soft-paper',
  'sage',
] as const;

export type ThemeMode = typeof THEME_MODE_OPTIONS[number];
export type ResolvedTheme = 'dark' | 'light';

export interface ThemeState {
  mode: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setMode: (mode: ThemeMode, options?: { persist?: boolean }) => void;
}

const STORAGE_KEY = 'magi-theme-mode';
const THEME_CLASS_NAMES = ['light', 'dark', ...THEME_MODE_OPTIONS.map((mode) => `theme-${mode}`)] as const;
const CUSTOM_THEME_CLASS_BY_MODE: Partial<Record<ThemeMode, string>> = {
  'warm-neutral': 'theme-warm-neutral',
  'cool-studio': 'theme-cool-studio',
  'soft-paper': 'theme-soft-paper',
  sage: 'theme-sage',
};

const isThemeMode = (value: string | null): value is ThemeMode => (
  Boolean(value) && THEME_MODE_OPTIONS.includes(value as ThemeMode)
);

const safeGetItem = (key: string): string | null => {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return null;
    }
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};

const safeSetItem = (key: string, value: string): void => {
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      return;
    }
    window.localStorage.setItem(key, value);
  } catch {
    // ignore storage failures
  }
};

const getSystemTheme = (): ResolvedTheme => {
  if (typeof window === 'undefined' || !window.matchMedia) {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const resolveTheme = (mode: ThemeMode): ResolvedTheme => {
  if (mode === 'system') {
    return getSystemTheme();
  }
  return mode === 'dark' ? 'dark' : 'light';
};

const syncDesktopCaptionColor = (): void => {
  if (typeof window === 'undefined') {
    return;
  }
  void import('@/runtime/desktop')
    .then(({ syncWindowCaptionColor }) => syncWindowCaptionColor())
    .catch(() => {
      // desktop runtime unavailable (web build)
    });
};

const applyTheme = (mode: ThemeMode, resolvedTheme = resolveTheme(mode)): void => {
  if (typeof document === 'undefined') {
    return;
  }
  const root = document.documentElement;
  root.classList.remove(...THEME_CLASS_NAMES);
  root.classList.add(resolvedTheme);

  const customClassName = CUSTOM_THEME_CLASS_BY_MODE[mode];
  if (customClassName) {
    root.classList.add(customClassName);
  }

  syncDesktopCaptionColor();
};

export const initializeTheme = (): { mode: ThemeMode; resolvedTheme: ResolvedTheme } => {
  const storedMode = safeGetItem(STORAGE_KEY);
  const mode: ThemeMode = isThemeMode(storedMode) ? storedMode : 'system';
  const resolvedTheme = resolveTheme(mode);

  if (typeof window !== 'undefined') {
    applyTheme(mode, resolvedTheme);
  }

  return { mode, resolvedTheme };
};

export const useThemeStore = create<ThemeState>((set) => {
  const initialTheme = initializeTheme();

  return {
    mode: initialTheme.mode,
    resolvedTheme: initialTheme.resolvedTheme,
    setMode: (mode, options) => {
      const resolved = resolveTheme(mode);
      if (options?.persist !== false) {
        safeSetItem(STORAGE_KEY, mode);
      }
      applyTheme(mode, resolved);
      set({ mode, resolvedTheme: resolved });
    },
  };
});

// Listen for system theme changes
if (typeof window !== 'undefined' && window.matchMedia) {
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  mediaQuery.addEventListener('change', (e) => {
    const state = useThemeStore.getState();
    if (state.mode === 'system') {
      const resolved = e.matches ? 'dark' : 'light';
      applyTheme(state.mode, resolved);
      useThemeStore.setState({ resolvedTheme: resolved });
    }
  });
}
