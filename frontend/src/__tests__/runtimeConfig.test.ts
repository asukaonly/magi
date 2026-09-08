import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }));
import { ensureRuntimeSession, getRuntimeConfig, initializeRuntime, normalizeApiBaseUrl, readBackendStartupDiagnostics, resetRuntimeInitialization } from '@/runtime/config';

const serverId = 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0';
const clientId = 'a0c4c092-b043-4767-a2a7-041ad6194b8c';
const started = (overrides = {}) => ({ ok: true, baseUrl: 'http://127.0.0.1:19080/api', sessionToken: 'a'.repeat(64), serverId, profileId: 'local', mode: 'local', dataEpoch: serverId, expiresAtMs: null, apiPid: 123, runtimeWorkerPid: null, ...overrides });

describe('center runtime bootstrap', () => {
  beforeEach(() => {
    vi.useRealTimers(); invokeMock.mockReset(); resetRuntimeInitialization();
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); delete (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__; });

  it('normalizes explicit bind addresses', () => {
    expect(normalizeApiBaseUrl('http://0.0.0.0:8000', '127.0.0.1')).toBe('http://127.0.0.1:8000/api');
  });
  it('rejects use outside the desktop host', async () => {
    delete (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__;
    await expect(initializeRuntime()).rejects.toThrow('requires Tauri');
    await expect(readBackendStartupDiagnostics()).resolves.toBeNull();
  });
  it('deduplicates bootstrap and accepts readiness from the authenticated native probe', async () => {
    invokeMock.mockImplementation(async (command) => command === 'start_backend' ? started() : { ready: true, phase: 'ready' });
    const first = initializeRuntime(); const second = initializeRuntime();
    expect(second).toBe(first);
    await expect(first).resolves.toMatchObject({ serverId, mode: 'local', apiPid: 123 });
    expect(invokeMock).toHaveBeenCalledTimes(2);
  });
  it('rejects a remote address without HTTPS', async () => {
    invokeMock.mockResolvedValue(started({ mode: 'remote' }));
    await expect(initializeRuntime()).rejects.toThrow('invalid API address');
  });
  it('rejects a late startup after the connection generation changed', async () => {
    let finish: (value: unknown) => void = () => undefined;
    invokeMock.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const pending = initializeRuntime();
    const rejected = expect(pending).rejects.toThrow('Connection changed');
    resetRuntimeInitialization(); finish(started()); await rejected;
    expect(getRuntimeConfig().serverId).toBeUndefined();
  });
  it('deduplicates expiring remote session renewal and validates center identity', async () => {
    invokeMock.mockImplementation(async (command) => command === 'start_backend'
      ? started({ mode: 'remote', profileId: clientId, baseUrl: 'https://center.example/api', expiresAtMs: 1 })
      : { ready: true, phase: 'ready' });
    await initializeRuntime();
    invokeMock.mockResolvedValue({ server_id: serverId, client_id: clientId, access_token: 'b'.repeat(64), expires_at_ms: Date.now() + 900_000 });
    const first = ensureRuntimeSession(); const second = ensureRuntimeSession(); expect(second).toBe(first);
    await expect(first).resolves.toBe('b'.repeat(64));
    expect(getRuntimeConfig().sessionToken).toBe('b'.repeat(64));
    expect(invokeMock.mock.calls.filter(([command]) => command === 'renew_center_session')).toHaveLength(1);
  });
  it('allows maintenance recovery to show without requiring ordinary runtime readiness', async () => {
    invokeMock.mockImplementation(async (command) => command === 'start_backend' ? started() : { ready: true, phase: 'recovering_data_clear' });
    const phases: string[] = [];
    await initializeRuntime((phase) => phases.push(phase));
    expect(phases.at(-1)).toBe('recovering_data_clear');
  });
});
