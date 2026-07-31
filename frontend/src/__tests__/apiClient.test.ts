import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  api,
  apiClient,
  configureApiClient,
  syncBackendHealthFromApiError,
  toApiClientError,
  unwrapGatewayPayload,
} from '@/api/client';
import { redactLogText } from '@/runtime/log-redaction';
import { useBackendHealthStore } from '@/stores/backend-health';

describe('api client helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    configureApiClient({ sessionToken: undefined });
    useBackendHealthStore.getState().setHealth('healthy');
  });

  it('registers request, response, and desktop credentials for log redaction', async () => {
    configureApiClient({ sessionToken: 'desktop-session-secret' });
    await apiClient.post(
      '/test-secret-registration',
      { api_key: 'request-secret-value' },
      {
        adapter: async (config) => ({
          config,
          data: { bot_token: 'response-secret-value' },
          headers: {},
          status: 200,
          statusText: 'OK',
        }),
      },
    );

    const redacted = redactLogText(
      'desktop-session-secret request-secret-value response-secret-value',
    );
    expect(redacted).toBe('[REDACTED] [REDACTED] [REDACTED]');
  });

  it('passes AbortSignal through get config instead of serializing it as query params', async () => {
    const signal = new AbortController().signal;
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { success: true, message: 'ok', data: { ok: true } },
    });

    await api.get('/memory/statistics', { signal });

    expect(getSpy).toHaveBeenCalledWith('/memory/statistics', { signal });
  });

  it('keeps shorthand query params for get calls', async () => {
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { success: true, message: 'ok', data: { items: [] } },
    });

    await api.get('/messages/history', { user_id: 'local_user', session_id: 'session-1' });

    expect(getSpy).toHaveBeenCalledWith('/messages/history', {
      params: { user_id: 'local_user', session_id: 'session-1' },
    });
  });

  it('classifies gateway and runtime readiness failures', () => {
    const error = toApiClientError({
      isAxiosError: true,
      message: 'Request failed with status code 503',
      response: {
        status: 503,
        data: {
          message: 'Runtime is still starting',
          error_code: 'RUNTIME_NOT_READY',
          details: { startup_state: 'starting' },
        },
      },
    });

    expect(error).toMatchObject({
      message: 'Runtime is still starting',
      code: 'RUNTIME_NOT_READY',
      kind: 'backend-not-ready',
      status: 503,
      details: { startup_state: 'starting' },
    });
  });

  it('reads stable error details nested by FastAPI', () => {
    const error = toApiClientError({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: {
          detail: {
            message: 'TUN fake-IP compatibility is required',
            error_code: 'FAKE_IP_COMPATIBILITY_REQUIRED',
          },
        },
      },
    });

    expect(error).toMatchObject({
      message: 'TUN fake-IP compatibility is required',
      code: 'FAKE_IP_COMPATIBILITY_REQUIRED',
      kind: 'http',
      status: 409,
    });
  });

  it('normalizes cancellation into a stable error kind', () => {
    const error = toApiClientError({
      isAxiosError: true,
      code: 'ERR_CANCELED',
      message: 'canceled',
    });

    expect(error).toEqual({
      message: 'Request cancelled',
      code: 'REQUEST_CANCELLED',
      kind: 'cancelled',
      isCancelled: true,
    });
  });

  it('unwraps Python envelopes while preserving Rust-native payloads', () => {
    expect(unwrapGatewayPayload({ success: true, message: 'ok', data: { count: 3 } })).toEqual({ count: 3 });
    expect(unwrapGatewayPayload({ items: [], total: 0, limit: 50, offset: 0 })).toEqual({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
  });

  it('syncs backend readiness errors into the health store', () => {
    syncBackendHealthFromApiError({
      message: 'Runtime is still starting',
      code: 'RUNTIME_NOT_READY',
      kind: 'backend-not-ready',
      status: 503,
      details: {
        runtime_status: 'starting',
        startup_state: 'deferred',
        deferred_reason: 'selection_pending',
        llm_ready: false,
        agent_runtime_ready: false,
      },
    });

    expect(useBackendHealthStore.getState()).toMatchObject({
      status: 'degraded',
      runtimeStatus: 'starting',
      startupState: 'deferred',
      deferredReason: 'selection_pending',
      llmReady: false,
      agentRuntimeReady: false,
    });
  });

  it('syncs network errors into offline health state', () => {
    syncBackendHealthFromApiError({
      message: 'No response from server',
      code: 'NETWORK_ERROR',
      kind: 'network',
    });

    expect(useBackendHealthStore.getState().status).toBe('offline');
  });
});
