/**
 * Central type exports for Magi frontend.
 */

// API types
export type {
  ApiResponse,
  ApiError,
  ApiClientError,
  PaginatedResponse,
  ApiRequestConfig,
  ApiPaginationParams,
} from './api';
export { isApiError, isApiClientError, isNetworkError } from './api';

// Re-export API types for convenience
export type { ExecutionTraceSummary } from './api';

// Common types
export type {
  ThemeMode,
  LanguageCode,
  User,
  AsyncStatus,
  AsyncState,
  Result,
  Success,
  Failure,
} from './common';
export {
  SUPPORTED_LANGUAGES,
  createInitialAsyncState,
  success,
  failure,
} from './common';
