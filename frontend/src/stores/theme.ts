import { create } from 'zustand';
import { syncWindowCaptionColor } from '@/runtime/desktop';

export const THEME_MODE_OPTIONS = [
  'light',
  'dark',
  'system',
  'apricot',
  'matcha',
  'persimmon',
  'mist',
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
  mist: 'theme-mist',
  matcha: 'theme-matcha',
  persimmon: 'theme-persimmon',
  apricot: 'theme-apricot',
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
  // runtime/desktop is already statically imported from main.tsx, so the
  // previous dynamic import bought nothing but a Vite/Rolldown warning
  // about ineffective dynamic import. `syncWindowCaptionColor` itself
  // no-ops cleanly when not running under Tauri.
  try {
    void syncWindowCaptionColor();
  } catch {
    // desktop runtime unavailable (web build) — swallow silently
  }
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
  // 新用户(无存储偏好)默认 apricot(主浅色);老用户保留已存储的选择。
  const mode: ThemeMode = isThemeMode(storedMode) ? storedMode : 'apricot';
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

// Listen for system theme changes.
//
// This runs at module evaluation time, so any path that re-imports this
// module (Vite HMR in dev, accidental dual-import in prod) would stack
// duplicate listeners and leak memory + double-apply themes. We guard
// with a module-scoped flag and stash the listener on `window` so an
// HMR cycle can dispose the previous one before binding a new one.
declare global {
  interface Window {
    __magiThemeMediaQuery?: MediaQueryList;
    __magiThemeMediaListener?: (event: MediaQueryListEvent) => void;
  }
}

if (typeof window !== 'undefined' && window.matchMedia) {
  const previousQuery = window.__magiThemeMediaQuery;
  const previousListener = window.__magiThemeMediaListener;
  if (previousQuery && previousListener) {
    previousQuery.removeEventListener('change', previousListener);
  }

  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  const listener = (event: MediaQueryListEvent) => {
    const state = useThemeStore.getState();
    if (state.mode === 'system') {
      const resolved = event.matches ? 'dark' : 'light';
      applyTheme(state.mode, resolved);
      useThemeStore.setState({ resolvedTheme: resolved });
    }
  };
  mediaQuery.addEventListener('change', listener);
  window.__magiThemeMediaQuery = mediaQuery;
  window.__magiThemeMediaListener = listener;
}
