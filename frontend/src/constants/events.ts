/**
 * Application-level custom events.
 *
 * These events are dispatched via window.dispatchEvent for cross-component
 * communication without tight coupling.
 */

// ============================================================================
// Event Names
// ============================================================================

export const APP_EVENTS = {
  /** Dispatched when memory is cleared */
  MEMORY_CLEARED: 'magi-memory-cleared',
  /** Dispatched when session state changes */
  SESSION_SYNC: 'magi-session-sync',
  /** Dispatched when theme changes */
  THEME_CHANGED: 'magi-theme-changed',
  /** Dispatched when language changes */
  LANGUAGE_CHANGED: 'magi-language-changed',
  /** Dispatched when settings are saved */
  SETTINGS_SAVED: 'magi-settings-saved',
  /** Dispatched when personality is switched */
  PERSONALITY_SWITCHED: 'magi-personality-switched',
} as const;

// ============================================================================
// Event Types
// ============================================================================

export interface MemoryClearedEvent extends CustomEvent {
  type: typeof APP_EVENTS.MEMORY_CLEARED;
}

export interface SessionSyncEvent extends CustomEvent {
  type: typeof APP_EVENTS.SESSION_SYNC;
}

export interface ThemeChangedEvent extends CustomEvent<{
  theme: 'light' | 'dark' | 'system';
}> {
  type: typeof APP_EVENTS.THEME_CHANGED;
}

export interface LanguageChangedEvent extends CustomEvent<{
  language: string;
}> {
  type: typeof APP_EVENTS.LANGUAGE_CHANGED;
}

// ============================================================================
// Event Dispatcher Helpers
// ============================================================================

export function dispatchCustomAppEvent<T = undefined>(
  eventName: string,
  detail?: T
): void {
  window.dispatchEvent(new CustomEvent(eventName, { detail }));
}

export function subscribeToAppEvent(
  eventName: string,
  handler: (event: Event) => void,
): () => void {
  window.addEventListener(eventName, handler);
  return () => window.removeEventListener(eventName, handler);
}

// ============================================================================
// Convenience Dispatchers
// ============================================================================

export const dispatchAppEvent = {
  memoryCleared: () => dispatchCustomAppEvent(APP_EVENTS.MEMORY_CLEARED),
  sessionSync: () => dispatchCustomAppEvent(APP_EVENTS.SESSION_SYNC),
  themeChanged: (theme: 'light' | 'dark' | 'system') =>
    dispatchCustomAppEvent(APP_EVENTS.THEME_CHANGED, { theme }),
  languageChanged: (language: string) =>
    dispatchCustomAppEvent(APP_EVENTS.LANGUAGE_CHANGED, { language }),
  settingsSaved: () => dispatchCustomAppEvent(APP_EVENTS.SETTINGS_SAVED),
  personalitySwitched: (name: string) =>
    dispatchCustomAppEvent(APP_EVENTS.PERSONALITY_SWITCHED, { name }),
};
