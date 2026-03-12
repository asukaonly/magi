import { create } from 'zustand';

export type ThemeMode = 'dark' | 'light' | 'system';

export interface ThemeState {
  mode: ThemeMode;
  resolvedTheme: 'dark' | 'light';
  setMode: (mode: ThemeMode, options?: { persist?: boolean }) => void;
}

const STORAGE_KEY = 'magi-theme-mode';

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

const getSystemTheme = (): 'dark' | 'light' => {
  if (typeof window === 'undefined' || !window.matchMedia) {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const resolveTheme = (mode: ThemeMode): 'dark' | 'light' => {
  if (mode === 'system') {
    return getSystemTheme();
  }
  return mode;
};

const applyTheme = (theme: 'dark' | 'light'): void => {
  if (typeof document === 'undefined') {
    return;
  }
  const root = document.documentElement;
  root.classList.remove('light', 'dark');
  root.classList.add(theme);
};

export const initializeTheme = (): { mode: ThemeMode; resolvedTheme: 'dark' | 'light' } => {
  const storedMode = safeGetItem(STORAGE_KEY) as ThemeMode | null;
  const mode: ThemeMode = storedMode || 'system';
  const resolvedTheme = resolveTheme(mode);

  if (typeof window !== 'undefined') {
    applyTheme(resolvedTheme);
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
      applyTheme(resolved);
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
      applyTheme(resolved);
      useThemeStore.setState({ resolvedTheme: resolved });
    }
  });
}
