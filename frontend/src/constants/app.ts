/**
 * Application-level constants.
 */

// ============================================================================
// User Identification
// ============================================================================

/** Default single-user desktop identity */
export const DEFAULT_USER_ID = 'local_user';

/** Default runtime namespace for the desktop shell */
export const DEFAULT_RUNTIME_NAMESPACE = 'desktop';

/** Default realtime channel for the local desktop user */
export const DEFAULT_USER_CHANNEL = `user_${DEFAULT_USER_ID}`;

/** Local storage key for current chat session */
export const CHAT_SESSION_KEY = (userId: string) => `chat_session_${userId}`;

// ============================================================================
// API Configuration
// ============================================================================

export const API_CONFIG = {
  /** Default request timeout (ms) */
  DEFAULT_TIMEOUT_MS: 30000,
  /** API version prefix */
  API_PREFIX: '/api',
} as const;

// ============================================================================
// UI Configuration
// ============================================================================

export const UI_CONFIG = {
  /** Default sidebar width (px) */
  SIDEBAR_WIDTH: 280,
  /** Minimum sidebar width (px) */
  SIDEBAR_MIN_WIDTH: 200,
  /** Maximum sidebar width (px) */
  SIDEBAR_MAX_WIDTH: 400,
  /** Chat message max width percentage */
  CHAT_MESSAGE_MAX_WIDTH_PERCENT: 75,
  /** Scroll to bottom behavior */
  SCROLL_BEHAVIOR: 'smooth' as const,
} as const;

// ============================================================================
// Local Storage Keys
// ============================================================================

export const STORAGE_KEYS = {
  AUTH_TOKEN: 'auth_token',
  LANGUAGE: 'magi_language',
  THEME: 'magi_theme',
  ONBOARDING_COMPLETED: 'magi_onboarding_completed',
} as const;

// ============================================================================
// Animation Constants
// ============================================================================

export const ANIMATION = {
  /** Default transition duration (ms) */
  DEFAULT_DURATION: 200,
  /** Fast transition duration (ms) */
  FAST_DURATION: 150,
  /** Slow transition duration (ms) */
  SLOW_DURATION: 300,
  /** Spring animation config */
  SPRING: {
    type: 'spring',
    stiffness: 300,
    damping: 30,
  },
} as const;
