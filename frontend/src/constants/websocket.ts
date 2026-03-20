/**
 * WebSocket configuration and event constants.
 */

// ============================================================================
// Connection Configuration
// ============================================================================

export const WS_CONFIG = {
  /** Maximum number of reconnection attempts */
  MAX_RECONNECT_ATTEMPTS: 10,
  /** Base delay between reconnection attempts (ms) */
  BASE_RECONNECT_DELAY_MS: 1000,
  /** Maximum delay between reconnection attempts (ms) */
  MAX_RECONNECT_DELAY_MS: 30000,
  /** Connection timeout (ms) */
  CONNECTION_TIMEOUT_MS: 5000,
  /** Jitter range for reconnection (ms) */
  RECONNECT_JITTER_MS: 1000,
} as const;

// ============================================================================
// Message Types (Server -> Client)
// ============================================================================

export const WS_MESSAGE_TYPES = {
  SUBSCRIBED: 'subscribed',
  HISTORY: 'history',
  PERSONALITY_INFO: 'personality_info',
  MESSAGE_SENT: 'message_sent',
  EXECUTION_TRACE_UPDATE: 'execution_trace_update',
  AGENT_RESPONSE: 'agent_response',
  ERROR: 'error',
  // Client message types (also used in server responses)
  GET_HISTORY: 'get_history',
  GET_PERSONALITY: 'get_personality',
  SEND_MESSAGE: 'send_message',
} as const;

// ============================================================================
// Message Types (Client -> Server)
// ============================================================================

export const WS_CLIENT_MESSAGE_TYPES = {
  SUBSCRIBE: 'subscribe',
  GET_HISTORY: 'get_history',
  GET_PERSONALITY: 'get_personality',
  SEND_MESSAGE: 'send_message',
} as const;

// ============================================================================
// WebSocket Ready States
// ============================================================================

export const WS_READY_STATE = {
  CONNECTING: 0,
  OPEN: 1,
  CLOSING: 2,
  CLOSED: 3,
} as const;

export type WSReadyState = typeof WS_READY_STATE[keyof typeof WS_READY_STATE];
