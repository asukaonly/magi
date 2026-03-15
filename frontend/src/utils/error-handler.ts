/**
 * Unified error handling utilities for Magi frontend.
 */

import { toast } from 'sonner';
import { isApiError, type ApiClientError } from '@/types';

// ============================================================================
// Error Types
// ============================================================================

export type ErrorSeverity = 'info' | 'warning' | 'error' | 'critical';

export interface AppError {
  message: string;
  code: string;
  severity: ErrorSeverity;
  details?: unknown;
  recoverable?: boolean;
}

// ============================================================================
// Error Factory Functions
// ============================================================================

/**
 * Handle API errors and convert to AppError.
 */
export function handleApiError(error: unknown, context?: string): AppError {
  // Network offline
  if (!navigator.onLine) {
    return {
      message: 'Network unavailable. Please check your connection.',
      code: 'NETWORK_OFFLINE',
      severity: 'warning',
      recoverable: true,
    };
  }

  // API error response
  if (isApiError(error)) {
    const severity = error.status === 401 ? 'critical' : 'error';
    return {
      message: error.message,
      code: error.error_code || 'API_ERROR',
      severity,
      details: error.details,
      recoverable: error.status !== 401,
    };
  }

  // Client error (from axios interceptor)
  if (isApiClientError(error)) {
    return {
      message: error.message,
      code: error.code,
      severity: error.code === 'NETWORK_ERROR' ? 'warning' : 'error',
      details: error.details,
      recoverable: error.code === 'NETWORK_ERROR',
    };
  }

  // Unknown error
  const contextMessage = context ? `${context} failed` : 'An unexpected error occurred';
  return {
    message: contextMessage,
    code: 'UNKNOWN_ERROR',
    severity: 'error',
    details: error,
    recoverable: false,
  };
}

/**
 * Handle WebSocket errors.
 */
export function handleWSError(error: unknown, context?: string): AppError {
  const message = error instanceof Error ? error.message : String(error);

  if (message.includes('WebSocket') || message.includes('connection')) {
    return {
      message: 'Connection lost. Reconnecting...',
      code: 'WS_CONNECTION_ERROR',
      severity: 'warning',
      details: error,
      recoverable: true,
    };
  }

  return {
    message: context ? `${context} failed` : message,
    code: 'WS_ERROR',
    severity: 'error',
    details: error,
    recoverable: false,
  };
}

/**
 * Create a validation error.
 */
export function createValidationError(message: string, field?: string): AppError {
  return {
    message,
    code: 'VALIDATION_ERROR',
    severity: 'warning',
    details: field ? { field } : undefined,
    recoverable: true,
  };
}

// ============================================================================
// Error Display Functions
// ============================================================================

/**
 * Display error to user via toast.
 */
export function showError(error: AppError): void {
  switch (error.severity) {
    case 'info':
      toast.info(error.message);
      break;
    case 'warning':
      toast.warning(error.message);
      break;
    case 'error':
    case 'critical':
      toast.error(error.message);
      break;
  }

  // Log details in development
  if (import.meta.env.DEV && error.details) {
    console.error(`[${error.code}]`, error.details);
  }
}

/**
 * Handle error with optional context and display.
 */
export function handleError(error: unknown, context?: string, display = true): AppError {
  const appError = handleApiError(error, context);

  if (display) {
    showError(appError);
  }

  return appError;
}

/**
 * Handle error silently (no toast, just logging).
 */
export function handleErrorSilent(error: unknown, context?: string): AppError {
  const appError = handleApiError(error, context);

  // Always log in development
  if (import.meta.env.DEV) {
    console.error(`[${appError.code}] ${context || 'Unknown context'}:`, error);
  }

  return appError;
}

// ============================================================================
// Try-Catch Wrapper
// ============================================================================

/**
 * Wrap an async function with error handling.
 */
export function withErrorHandling<T>(
  fn: () => Promise<T>,
  options: {
    context?: string;
    display?: boolean;
    onError?: (error: AppError) => void;
  } = {}
): Promise<T | null> {
  const { context, display = true, onError } = options;

  return fn().catch((error) => {
    const appError = handleApiError(error, context);

    if (display) {
      showError(appError);
    }

    onError?.(appError);

    return null;
  });
}

/**
 * Create a safe async handler for event handlers.
 */
export function createSafeHandler<T extends unknown[], R>(
  fn: (...args: T) => Promise<R>,
  options: {
    context?: string;
    display?: boolean;
    fallback?: R;
  } = {}
): (...args: T) => Promise<R | null> {
  const { context, display = true, fallback } = options;

  return async (...args: T) => {
    try {
      return await fn(...args);
    } catch (error) {
      const appError = handleApiError(error, context);

      if (display) {
        showError(appError);
      }

      return fallback ?? null;
    }
  };
}

// ============================================================================
// Type Guard
// ============================================================================

function isApiClientError(error: unknown): error is ApiClientError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    'code' in error
  );
}
