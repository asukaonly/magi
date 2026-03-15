/**
 * API response and error types for Magi.
 */

// ============================================================================
// Generic API Types
// ============================================================================

export interface ApiResponse<T = unknown> {
  success: boolean;
  message: string;
  data?: T;
}

export interface ApiError {
  success: false;
  message: string;
  detail?: string;
  error_code?: string;
  details?: unknown;
  status?: number;
}

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ============================================================================
// API Client Error (thrown by interceptors)
// ============================================================================

export interface ApiClientError {
  message: string;
  code: string;
  status?: number;
  details?: unknown;
}

// ============================================================================
// Type Guards
// ============================================================================

export function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'success' in error &&
    error.success === false &&
    'message' in error
  );
}

export function isApiClientError(error: unknown): error is ApiClientError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'message' in error &&
    'code' in error
  );
}

export function isNetworkError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    (error as ApiClientError).code === 'NETWORK_ERROR'
  );
}

// ============================================================================
// Request Config Types
// ============================================================================

export interface ApiRequestConfig {
  params?: Record<string, unknown>;
  headers?: Record<string, string>;
  timeout?: number;
  signal?: AbortSignal;
}

export interface ApiPaginationParams {
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
}

// Re-export from API modules
export type { ExecutionTraceSummary } from '@/api/modules/messages';
