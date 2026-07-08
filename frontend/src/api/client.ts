/**
 * Axios API client.
 */
import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { AxiosRequestConfig, AxiosResponse } from 'axios';
import { getRuntimeConfig } from '@/runtime/config';
import { useBackendHealthStore } from '@/stores/backend-health';
import { resolveInitialLanguage } from '@/utils/language';

// API response types
export interface ApiResponse<T = unknown> {
  success: boolean;
  message: string;
  data?: T;
}

export type GatewayResponse<T> = ApiResponse<T> | T;

export interface ApiError {
  success: false;
  message: string;
  detail?: string;
  error_code?: string;
  details?: unknown;
}

export type ApiClientErrorKind = 'http' | 'network' | 'backend-not-ready' | 'cancelled' | 'request';

export interface ApiClientError {
  message: string;
  code: string;
  kind: ApiClientErrorKind;
  status?: number;
  details?: unknown;
  isCancelled?: boolean;
}

export type ApiRequestConfig = AxiosRequestConfig;

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// Create axios instance
let desktopSessionToken: string | undefined;

const AXIOS_CONFIG_KEYS = new Set([
  'adapter',
  'auth',
  'baseURL',
  'cancelToken',
  'data',
  'headers',
  'maxBodyLength',
  'maxContentLength',
  'method',
  'onDownloadProgress',
  'onUploadProgress',
  'params',
  'paramsSerializer',
  'responseType',
  'signal',
  'timeout',
  'transformRequest',
  'transformResponse',
  'url',
  'validateStatus',
  'withCredentials',
]);

const BACKEND_NOT_READY_CODES = new Set([
  'BACKEND_NOT_READY',
  'GATEWAY_TIMEOUT',
  'IPC_UNAVAILABLE',
  'RUNTIME_NOT_READY',
  'SERVICE_UNAVAILABLE',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function looksLikeAxiosConfig(value: unknown): value is ApiRequestConfig {
  if (!isRecord(value)) {
    return false;
  }
  return Object.keys(value).some((key) => AXIOS_CONFIG_KEYS.has(key));
}

function normalizeGetConfig(paramsOrConfig?: unknown): ApiRequestConfig | undefined {
  if (paramsOrConfig == null) {
    return undefined;
  }
  if (looksLikeAxiosConfig(paramsOrConfig)) {
    return paramsOrConfig;
  }
  return { params: paramsOrConfig };
}

function extractDetailMessage(detail: unknown): string | undefined {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (isRecord(item) && typeof item.msg === 'string' ? item.msg : undefined))
      .filter((message): message is string => Boolean(message));
    return messages.length > 0 ? messages.join('; ') : undefined;
  }
  return undefined;
}

function extractResponseMessage(data: unknown, fallback: string): string {
  if (typeof data === 'string') {
    return data;
  }
  if (!isRecord(data)) {
    return fallback;
  }
  if (typeof data.message === 'string') {
    return data.message;
  }
  const detailMessage = extractDetailMessage(data.detail);
  if (detailMessage) {
    return detailMessage;
  }
  if (typeof data.error === 'string') {
    return data.error;
  }
  return fallback;
}

function extractErrorCode(data: unknown): string | undefined {
  if (!isRecord(data)) {
    return undefined;
  }
  if (typeof data.error_code === 'string') {
    return data.error_code;
  }
  if (typeof data.code === 'string') {
    return data.code;
  }
  return undefined;
}

function extractErrorDetails(data: unknown): unknown {
  if (!isRecord(data)) {
    return undefined;
  }
  return data.details ?? data.detail;
}

function classifyHttpError(status: number, code: string): ApiClientErrorKind {
  if (status === 502 || status === 503 || status === 504 || BACKEND_NOT_READY_CODES.has(code)) {
    return 'backend-not-ready';
  }
  return 'http';
}

export function toApiClientError(error: unknown): ApiClientError {
  if (axios.isCancel(error) || (isRecord(error) && error.code === 'ERR_CANCELED')) {
    return {
      message: 'Request cancelled',
      code: 'REQUEST_CANCELLED',
      kind: 'cancelled',
      isCancelled: true,
    };
  }

  if (axios.isAxiosError<ApiError>(error)) {
    if (error.response) {
      const errorData = error.response.data;
      const code = extractErrorCode(errorData) || 'UNKNOWN_ERROR';
      return {
        message: extractResponseMessage(errorData, error.message || 'Request failed'),
        code,
        kind: classifyHttpError(error.response.status, code),
        status: error.response.status,
        details: extractErrorDetails(errorData),
      };
    }
    if (error.request) {
      return {
        message: 'No response from server',
        code: 'NETWORK_ERROR',
        kind: 'network',
      };
    }
    return {
      message: error.message || 'Request failed',
      code: 'REQUEST_ERROR',
      kind: 'request',
    };
  }

  return {
    message: error instanceof Error ? error.message : 'Request failed',
    code: 'REQUEST_ERROR',
    kind: 'request',
  };
}

function getBooleanDetail(details: Record<string, unknown> | undefined, key: string): boolean | null {
  return typeof details?.[key] === 'boolean' ? details[key] : null;
}

function getStringDetail(details: Record<string, unknown> | undefined, key: string): string | null {
  return typeof details?.[key] === 'string' ? details[key] : null;
}

export function syncBackendHealthFromApiError(error: ApiClientError): void {
  if (error.kind !== 'backend-not-ready' && error.kind !== 'network') {
    return;
  }

  const details = isRecord(error.details) ? error.details : undefined;
  if (error.kind === 'backend-not-ready') {
    useBackendHealthStore.getState().setHealth('degraded', {
      runtimeStatus: getStringDetail(details, 'runtime_status') ?? error.code,
      startupState: getStringDetail(details, 'startup_state'),
      deferredReason: getStringDetail(details, 'deferred_reason') ?? error.message,
      llmReady: getBooleanDetail(details, 'llm_ready'),
      agentRuntimeReady: getBooleanDetail(details, 'agent_runtime_ready'),
    });
    return;
  }

  useBackendHealthStore.getState().setHealth('offline');
}

function unwrapApiResponse<T>(response: AxiosResponse<ApiResponse<T>>): ApiResponse<T> {
  return response.data;
}

export function unwrapGatewayPayload<T>(response: GatewayResponse<T>): T {
  if (isRecord(response) && 'success' in response && 'data' in response) {
    return response.data as T;
  }
  return response as T;
}

const createApiClient = (): AxiosInstance => {
  const runtime = getRuntimeConfig();
  const client = axios.create({
    baseURL: runtime.apiBaseUrl,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // Request interceptor
  client.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      const runtime = getRuntimeConfig();
      const sessionToken = desktopSessionToken || runtime.sessionToken;
      if (sessionToken && config.headers) {
        config.headers['X-Magi-Session-Token'] = sessionToken;
      }
      // Add language header
      const language = resolveInitialLanguage();
      if (config.headers) {
        config.headers['Accept-Language'] = language;
      }
      return config;
    },
    (error) => {
      return Promise.reject(error);
    }
  );

  // Response interceptor
  client.interceptors.response.use(
    (response) => {
      return response;
    },
    (error: AxiosError<ApiError>) => {
      const clientError = toApiClientError(error);
      syncBackendHealthFromApiError(clientError);
      return Promise.reject(clientError);
    }
  );

  return client;
};

export const apiClient = createApiClient();

/**
 * Returns the API base URL prefix that {@link apiClient} uses. Useful for
 * code paths (e.g. streaming) that bypass axios and call `fetch` directly.
 */
export function resolveApiBaseUrl(): string {
  const configured = apiClient.defaults.baseURL;
  if (configured) {
    return configured.replace(/\/+$/, '');
  }
  return getRuntimeConfig().apiBaseUrl.replace(/\/+$/, '');
}

export const configureApiClient = (options: {
  baseUrl?: string;
  sessionToken?: string;
} = {}): void => {
  if (options.baseUrl) {
    apiClient.defaults.baseURL = options.baseUrl.replace(/\/+$/, '');
  }
  desktopSessionToken = options.sessionToken;
  if (desktopSessionToken) {
    apiClient.defaults.headers.common['X-Magi-Session-Token'] = desktopSessionToken;
  } else {
    delete apiClient.defaults.headers.common['X-Magi-Session-Token'];
  }
};

// Generic API helpers.
//
// The response type parameter defaults to `unknown` (not `any`) so callers
// that omit the type get a value they MUST narrow before use. This is the
// Lv1 boundary-tightening pass — every call site that previously relied on
// `any`'s structural permissiveness now has to declare what it expects.
export const api = {
  get: <T = unknown>(url: string, paramsOrConfig?: Record<string, unknown> | ApiRequestConfig) => {
    const config = normalizeGetConfig(paramsOrConfig);
    return apiClient.get<ApiResponse<T>>(url, config).then(unwrapApiResponse);
  },

  post: <T = unknown>(url: string, data?: unknown, config?: ApiRequestConfig) =>
    apiClient.post<ApiResponse<T>>(url, data, config).then(unwrapApiResponse),

  put: <T = unknown>(url: string, data?: unknown, config?: ApiRequestConfig) =>
    apiClient.put<ApiResponse<T>>(url, data, config).then(unwrapApiResponse),

  delete: <T = unknown>(url: string, config?: ApiRequestConfig) =>
    apiClient.delete<ApiResponse<T>>(url, config).then(unwrapApiResponse),

  patch: <T = unknown>(url: string, data?: unknown, config?: ApiRequestConfig) =>
    apiClient.patch<ApiResponse<T>>(url, data, config).then(unwrapApiResponse),
};

export default apiClient;
