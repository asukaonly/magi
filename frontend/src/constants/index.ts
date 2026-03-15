/**
 * Central constant exports for Magi frontend.
 */

// WebSocket constants
export {
  WS_CONFIG,
  WS_MESSAGE_TYPES,
  WS_CLIENT_MESSAGE_TYPES,
  WS_READY_STATE,
} from './websocket';
export type { WSReadyState } from './websocket';

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
  CHAT_SESSION_KEY,
  API_CONFIG,
  UI_CONFIG,
  STORAGE_KEYS,
  ANIMATION,
} from './app';
