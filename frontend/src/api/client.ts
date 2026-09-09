/**
 * Axios API client.
 */
import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { AxiosRequestConfig, AxiosResponse } from 'axios';
import { getRuntimeConfig, getRuntimeGeneration, ensureRuntimeSession, recoverRuntimeSession, subscribeRuntimeReset } from '@/runtime/config';
import { registerKnownLogSecrets } from '@/runtime/log-redaction';
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
type ApiScope = { baseUrl: string; token?: string; owner: number; abort: AbortController };
let apiScope: ApiScope = {
  baseUrl: getRuntimeConfig().apiBaseUrl, owner: getRuntimeGeneration(), abort: new AbortController(),
};
const requestScopes = new WeakMap<InternalAxiosRequestConfig, ApiScope>();
function assertScope(scope: ApiScope): void {
  if (scope !== apiScope || scope.abort.signal.aborted || scope.owner !== getRuntimeGeneration()) {
    throw new axios.CanceledError('Connection changed');
  }
}
function requireOwnedUrl(input: string, scope: ApiScope): void {
  const url = new URL(input, `${scope.baseUrl}/`);
  const base = new URL(scope.baseUrl);
  if (url.origin !== base.origin || url.username || url.password || url.hash) {
    throw new Error('Authenticated requests must stay on the active center');
  }
}
async function sessionForScope(scope: ApiScope): Promise<string | undefined> {
  assertScope(scope);
  const token = await ensureRuntimeSession(scope.owner);
  assertScope(scope);
  return token ?? scope.token;
}
subscribeRuntimeReset(() => { apiScope.abort.abort(); });

function isSessionRejection(status: number | undefined, data: unknown): boolean {
  return status === 401 && typeof data === 'object' && data !== null
    && 'error_code' in data && data.error_code === 'client_auth_required';
}

function isReadRequest(method: string): boolean {
  return ['GET', 'HEAD'].includes(method.toUpperCase());
}

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
  if (isRecord(data.detail) && typeof data.detail.message === 'string') {
    return data.detail.message;
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
  if (isRecord(data.detail) && typeof data.detail.error_code === 'string') {
    return data.detail.error_code;
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
    adapter: 'fetch',
    fetchOptions: { redirect: 'error', credentials: 'omit' },
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // Request interceptor
  client.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      const scope = apiScope;
      assertScope(scope);
      const base = config.baseURL ?? scope.baseUrl;
      requireOwnedUrl(base, scope);
      requireOwnedUrl(new URL(config.url ?? '', `${base.replace(/\/+$/, '')}/`).toString(), scope);
      requestScopes.set(config, scope);
      // Capture ownership synchronously, before session renewal or adapter work yields.
      const adapter = axios.getAdapter(config.adapter ?? 'fetch');
      const originalSignal = config.signal;
      const abort = new AbortController();
      const cancel = () => abort.abort();
      originalSignal?.addEventListener?.('abort', cancel);
      scope.abort.signal.addEventListener('abort', cancel);
      if (originalSignal?.aborted || scope.abort.signal.aborted) cancel();
      config.signal = abort.signal;
      config.fetchOptions = { ...config.fetchOptions, redirect: 'error', credentials: 'omit' };
      config.adapter = async (request) => {
        try {
          const token = await sessionForScope(scope);
          if (abort.signal.aborted) throw new axios.CanceledError('Request cancelled');
          request.headers.delete('X-Magi-Session-Token');
          if (token) request.headers.set('X-Magi-Session-Token', token);
          registerKnownLogSecrets({ headers: request.headers });
          let response: AxiosResponse;
          try {
            response = await adapter(request);
          } catch (error: unknown) {
            if (!axios.isAxiosError<unknown>(error)
              || !isSessionRejection(error.response?.status, error.response?.data)) throw error;
            assertScope(scope);
            const refreshed = await recoverRuntimeSession(token, scope.owner);
            assertScope(scope);
            if (!refreshed || !isReadRequest(request.method ?? 'GET')) throw error;
            if (abort.signal.aborted) throw new axios.CanceledError('Request cancelled');
            request.headers.set('X-Magi-Session-Token', refreshed);
            registerKnownLogSecrets({ headers: request.headers });
            // Retry an authenticated read once. Writes and uncertain network failures are never replayed.
            response = await adapter(request);
          }
          assertScope(scope);
          return response;
        } finally {
          originalSignal?.removeEventListener?.('abort', cancel);
          scope.abort.signal.removeEventListener('abort', cancel);
        }
      };
      // Add language header
      const language = resolveInitialLanguage();
      if (config.headers) {
        config.headers['Accept-Language'] = language;
      }
      registerKnownLogSecrets({
        auth: config.auth,
        data: config.data as unknown,
        headers: config.headers,
        params: config.params as unknown,
      });
      return config;
    },
    (error: unknown) => { throw error; },
    { synchronous: true },
  );

  // Response interceptor
  client.interceptors.response.use(
    (response) => {
      const scope = requestScopes.get(response.config);
      if (scope) assertScope(scope);
      registerKnownLogSecrets(response.data);
      return response;
    },
    (error: AxiosError<ApiError>) => {
      const scope = error.config ? requestScopes.get(error.config) : undefined;
      if (scope && (scope !== apiScope || scope.abort.signal.aborted)) {
        return Promise.reject(toApiClientError(new axios.CanceledError('Connection changed')));
      }
      registerKnownLogSecrets({
        config: error.config,
        response: error.response?.data,
      });
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

export function getDesktopSessionToken(): string | undefined {
  return getRuntimeConfig().sessionToken ?? apiScope.token;
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const scope = apiScope;
  const target = input instanceof Request ? input.url : String(input);
  requireOwnedUrl(target, scope);
  const token = await sessionForScope(scope);
  const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
  headers.delete('X-Magi-Session-Token');
  if (token) headers.set('X-Magi-Session-Token', token);
  headers.set('Accept-Language', resolveInitialLanguage());
  const sourceSignal = init.signal ?? (input instanceof Request ? input.signal : undefined);
  const signal = sourceSignal ? AbortSignal.any([scope.abort.signal, sourceSignal]) : scope.abort.signal;
  registerKnownLogSecrets({ body: init.body, headers: Object.fromEntries(headers.entries()) });
  let response = await fetch(input, { ...init, headers, signal, redirect: 'error', credentials: 'omit' });
  assertScope(scope);
  if (response.status === 401) {
    const payload: unknown = await response.clone().json().catch(() => undefined);
    if (isSessionRejection(response.status, payload)) {
      const refreshed = await recoverRuntimeSession(token, scope.owner);
      assertScope(scope);
      const method = init.method ?? (input instanceof Request ? input.method : 'GET');
      if (refreshed && isReadRequest(method)) {
        await response.body?.cancel();
        headers.set('X-Magi-Session-Token', refreshed);
        registerKnownLogSecrets({ headers: Object.fromEntries(headers.entries()) });
        response = await fetch(input, { ...init, headers, signal, redirect: 'error', credentials: 'omit' });
        assertScope(scope);
      }
    }
  }
  return response;
}

export const configureApiClient = (options: {
  baseUrl?: string;
  sessionToken?: string;
} = {}): void => {
  registerKnownLogSecrets(options);
  apiScope.abort.abort();
  const baseUrl = (options.baseUrl ?? getRuntimeConfig().apiBaseUrl).replace(/\/+$/, '');
  apiScope = { baseUrl, token: options.sessionToken, owner: getRuntimeGeneration(), abort: new AbortController() };
  apiClient.defaults.baseURL = baseUrl;
  // Credentials belong to the dispatch scope, never to shared Axios defaults.
  delete apiClient.defaults.headers.common['X-Magi-Session-Token'];
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
