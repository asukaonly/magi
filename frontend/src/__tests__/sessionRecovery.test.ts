import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import axios, { AxiosError, type AxiosAdapter } from 'axios';
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
import { apiClient, authenticatedFetch, configureApiClient } from '@/api/client';
import { getRuntimeConfig, getRuntimeGeneration, initializeRuntime, recoverRuntimeSession, resetRuntimeInitialization } from '@/runtime/config';

const serverId = 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0';
const clientId = 'a0c4c092-b043-4767-a2a7-041ad6194b8c';
const oldToken = 'a'.repeat(64);
const newToken = 'b'.repeat(64);
const session = () => ({ server_id: serverId, client_id: clientId, access_token: newToken, expires_at_ms: Date.now() + 900_000 });
const rejection = { success: false, error_code: 'client_auth_required', message: 'Client authentication is required' };

beforeEach(async () => {
  resetRuntimeInitialization();
  invokeMock.mockReset();
  (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation(async (command) => command === 'connect_active_profile' ? {
    ok: true, connectionGeneration: 1, baseUrl: 'https://center.example/api', sessionToken: oldToken,
    serverId, profileId: clientId, mode: 'remote', dataEpoch: serverId, contentEpoch: serverId,
    expiresAtMs: Date.now() + 900_000, localServicePid: null,
  } : command === 'renew_center_session' ? session() : { connectionGeneration: 1, ready: true, phase: 'ready' });
  const runtime = await initializeRuntime();
  configureApiClient({ baseUrl: runtime.apiBaseUrl, sessionToken: runtime.sessionToken });
});
afterEach(() => {
  resetRuntimeInitialization();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__;
});

function rejectingAdapter(code = 'client_auth_required') {
  const calls: string[] = [];
  const adapter: AxiosAdapter = async (config) => {
    calls.push(String(config.headers.get('X-Magi-Session-Token')));
    if (calls.length === 1) {
      throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, undefined, {
        data: { ...rejection, error_code: code }, status: 401, statusText: 'Unauthorized', headers: {}, config,
      });
    }
    return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
  };
  return { calls, adapter };
}

describe('remote session recovery', () => {
  it('renews an unexpired invalid session and retries an Axios read once', async () => {
    const { calls, adapter } = rejectingAdapter();
    await expect(apiClient.get('/server/info', { adapter })).resolves.toMatchObject({ status: 200 });
    expect(calls).toEqual([oldToken, newToken]);
  });

  it('does not replay a write even after repairing its session', async () => {
    const { calls, adapter } = rejectingAdapter();
    await expect(apiClient.post('/tasks', { action: 'run' }, { adapter })).rejects.toMatchObject({ status: 401 });
    expect(calls).toEqual([oldToken]);
    expect(getRuntimeConfig().sessionToken).toBe(newToken);
  });

  it('does not interpret a provider authentication error as a gateway session error', async () => {
    const { calls, adapter } = rejectingAdapter('provider_unauthorized');
    await expect(apiClient.get('/provider/test', { adapter })).rejects.toMatchObject({ status: 401 });
    expect(calls).toEqual([oldToken]);
    expect(invokeMock.mock.calls.filter(([name]) => name === 'renew_center_session')).toHaveLength(0);
  });

  it('repairs the fetch path used by event streams', async () => {
    const tokens: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      tokens.push(new Headers(init.headers).get('X-Magi-Session-Token')!);
      return tokens.length === 1 ? new Response(JSON.stringify(rejection), { status: 401 }) : new Response('event: connected\n\n');
    }));
    await expect(authenticatedFetch('https://center.example/api/events')).resolves.toMatchObject({ status: 200 });
    expect(tokens).toEqual([oldToken, newToken]);
  });

  it('does not replay fetch mutations', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(rejection), { status: 401 }));
    vi.stubGlobal('fetch', fetch);
    await expect(authenticatedFetch('https://center.example/api/tasks', { method: 'POST', body: '{}' })).resolves.toMatchObject({ status: 401 });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it('coalesces concurrent failures and ignores late rejection of the old token', async () => {
    const owner = getRuntimeGeneration();
    const first = recoverRuntimeSession(oldToken, owner);
    const second = recoverRuntimeSession(oldToken, owner);
    expect(first).toBe(second);
    await first;
    await recoverRuntimeSession(oldToken, owner);
    expect(invokeMock.mock.calls.filter(([name]) => name === 'renew_center_session')).toHaveLength(1);
  });

  it('does not install a renewed session after switching connections', async () => {
    let finish: (value: unknown) => void = () => undefined;
    invokeMock.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = recoverRuntimeSession(oldToken, getRuntimeGeneration());
    const rejected = expect(pending).rejects.toThrow('Connection changed');
    resetRuntimeInitialization();
    finish(session());
    await rejected;
    expect(getRuntimeConfig().sessionToken).toBeUndefined();
  });

  it('throttles renewal failures instead of repeatedly sending revoked credentials', async () => {
    invokeMock.mockRejectedValue(new Error('Device credential revoked'));
    const owner = getRuntimeGeneration();
    await expect(recoverRuntimeSession(oldToken, owner)).rejects.toThrow('revoked');
    await expect(recoverRuntimeSession(oldToken, owner)).rejects.toThrow('revoked');
    expect(invokeMock).toHaveBeenCalledTimes(3);
  });

  it('never retries an uncertain network failure', async () => {
    const adapter = vi.fn<AxiosAdapter>().mockRejectedValue(new axios.AxiosError('Network Error', 'ERR_NETWORK', undefined, {}));
    await expect(apiClient.post('/tasks', {}, { adapter })).rejects.toMatchObject({ kind: 'network' });
    expect(adapter).toHaveBeenCalledOnce();
  });
});
