/**
 * Application-level custom events.
 *
 * These events are dispatched via window.dispatchEvent for cross-component
 * communication without tight coupling.
 */

import { advanceBrowserContentGeneration } from '@/lib/browserContentGeneration';

// ============================================================================
// Event Names
// ============================================================================

export const APP_EVENTS = {
  /** Dispatched before the durable clear request to retire in-flight writes. */
  MEMORY_CLEAR_STARTED: 'magi-memory-clear-started',
  /** Dispatched when a durable clear remains pending and the product must stay blocked. */
  MEMORY_CLEAR_FAILED: 'magi-memory-clear-failed',
  /** Releases only the interaction gate after a retry confirms no marker exists. */
  MEMORY_CLEAR_RECOVERY_RELEASED: 'magi-memory-clear-recovery-released',
  /** Dispatched when memory is cleared */
  MEMORY_CLEARED: 'magi-memory-cleared',
  /** Dispatched after one chat session is durably deleted */
  CHAT_SESSION_DELETED: 'magi-chat-session-deleted',
  /** Dispatched after one chat session's history is durably cleared */
  CHAT_HISTORY_CLEARED: 'magi-chat-history-cleared',
  /** Dispatched when session state changes */
  SESSION_SYNC: 'magi-session-sync',
  /** Dispatched when the installed/connected plugin set changes (install/enable
   *  completed), so system suggestions can re-evaluate and drop connected plugins */
  PLUGINS_CHANGED: 'magi-plugins-changed',
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

export interface MemoryClearFailedEvent extends CustomEvent<{
  message: string;
}> {
  type: typeof APP_EVENTS.MEMORY_CLEAR_FAILED;
}

export interface ChatSessionDeletedEvent extends CustomEvent<{
  sessionId: string;
}> {
  type: typeof APP_EVENTS.CHAT_SESSION_DELETED;
}

export interface ChatHistoryClearedEvent extends CustomEvent<{
  sessionId: string;
}> {
  type: typeof APP_EVENTS.CHAT_HISTORY_CLEARED;
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
  memoryClearStarted: () => {
    advanceBrowserContentGeneration();
    dispatchCustomAppEvent(APP_EVENTS.MEMORY_CLEAR_STARTED);
  },
  memoryClearFailed: (message: string) => dispatchCustomAppEvent(
    APP_EVENTS.MEMORY_CLEAR_FAILED,
    { message },
  ),
  memoryClearRecoveryReleased: () => dispatchCustomAppEvent(
    APP_EVENTS.MEMORY_CLEAR_RECOVERY_RELEASED,
  ),
  memoryCleared: () => dispatchCustomAppEvent(APP_EVENTS.MEMORY_CLEARED),
  chatSessionDeleted: (sessionId: string) => dispatchCustomAppEvent(
    APP_EVENTS.CHAT_SESSION_DELETED,
    { sessionId },
  ),
  chatHistoryCleared: (sessionId: string) => dispatchCustomAppEvent(
    APP_EVENTS.CHAT_HISTORY_CLEARED,
    { sessionId },
  ),
  sessionSync: () => dispatchCustomAppEvent(APP_EVENTS.SESSION_SYNC),
  pluginsChanged: () => dispatchCustomAppEvent(APP_EVENTS.PLUGINS_CHANGED),
  themeChanged: (theme: 'light' | 'dark' | 'system') =>
    dispatchCustomAppEvent(APP_EVENTS.THEME_CHANGED, { theme }),
  languageChanged: (language: string) =>
    dispatchCustomAppEvent(APP_EVENTS.LANGUAGE_CHANGED, { language }),
  settingsSaved: () => dispatchCustomAppEvent(APP_EVENTS.SETTINGS_SAVED),
  personalitySwitched: (name: string) =>
    dispatchCustomAppEvent(APP_EVENTS.PERSONALITY_SWITCHED, { name }),
};
