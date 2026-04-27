import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, apiClient, toApiClientError, unwrapGatewayPayload } from '@/api/client';

describe('api client helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks();
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
});