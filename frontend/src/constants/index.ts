/**
 * Central constant exports for Magi frontend.
 */

// Application events
export {
  APP_EVENTS,
  dispatchAppEvent,
  subscribeToAppEvent,
} from './events';
export type {
  MemoryClearedEvent,
  SessionSyncEvent,
  ThemeChangedEvent,
  LanguageChangedEvent,
} from './events';

// Application constants
export {
  DEFAULT_USER_ID,
  DEFAULT_RUNTIME_NAMESPACE,
  DEFAULT_USER_CHANNEL,
  CHAT_SESSION_KEY,
  API_CONFIG,
  UI_CONFIG,
  STORAGE_KEYS,
  ANIMATION,
} from './app';
