/**
 * Common application types.
 */

// ============================================================================
// Theme Types
// ============================================================================

export type { ThemeMode } from '@/stores/theme';

// ============================================================================
// Language Types
// ============================================================================

export type LanguageCode = 'en' | 'zh-CN';

export const SUPPORTED_LANGUAGES: LanguageCode[] = ['en', 'zh-CN'];

// ============================================================================
// User Types
// ============================================================================

export interface User {
  id: string;
  displayName?: string;
}

// ============================================================================
// Async State Types
// ============================================================================

export type AsyncStatus = 'idle' | 'loading' | 'success' | 'error';

export interface AsyncState<T, E = Error> {
  status: AsyncStatus;
  data: T | null;
  error: E | null;
}

export function createInitialAsyncState<T>(): AsyncState<T> {
  return {
    status: 'idle',
    data: null,
    error: null,
  };
}

// ============================================================================
// Result Types (for functional error handling)
// ============================================================================

export type Result<T, E = Error> = Success<T> | Failure<E>;

export interface Success<T> {
  ok: true;
  value: T;
}

export interface Failure<E> {
  ok: false;
  error: E;
}

export function success<T>(value: T): Success<T> {
  return { ok: true, value };
}

export function failure<E>(error: E): Failure<E> {
  return { ok: false, error };
}
