import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: invokeMock,
}));

import {
  buildWsBaseUrl,
  initializeRuntime,
  normalizeApiBaseUrl,
  normalizeConnectableUrl,
  resetRuntimeInitialization,
} from '@/runtime/config';

describe('runtime config URL normalization', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    invokeMock.mockReset();
    resetRuntimeInitialization();
    delete window.__MAGI_RUNTIME__;
    delete (window as Window & { __TAURI__?: object }).__TAURI__;
    delete (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('replaces restricted bind hosts with a connectable host for API URLs', () => {
    expect(normalizeApiBaseUrl('http://0.0.0.0:8000/api', '127.0.0.1')).toBe('http://127.0.0.1:8000/api');
  });

  it('preserves explicit connectable hosts', () => {
    expect(normalizeConnectableUrl('http://localhost:8000/api', '127.0.0.1')).toBe('http://localhost:8000/api');
  });

  it('derives websocket URLs from the sanitized API origin', () => {
    expect(buildWsBaseUrl(normalizeApiBaseUrl('http://0.0.0.0:8000/api', 'localhost'))).toBe('ws://localhost:8000');
  });

  it('waits for the backend ready probe before resolving in web mode', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        data: { ready: false, status: 'starting' },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        data: { ready: true, status: 'ready' },
      }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const runtimePromise = initializeRuntime();
    await vi.advanceTimersByTimeAsync(250);
    const runtime = await runtimePromise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://localhost:8000/api/ready',
      expect.objectContaining({ method: 'GET' })
    );
    expect(runtime.apiBaseUrl).toBe('http://localhost:8000/api');
  });

  it('waits for the backend ready probe after starting the desktop sidecar', async () => {
    vi.useFakeTimers();
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    invokeMock.mockResolvedValue({
      ok: true,
      baseUrl: 'http://127.0.0.1:8000/api',
      wsBaseUrl: 'ws://127.0.0.1:8000',
      sessionToken: 'token-1',
      pid: 4321,
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        data: { ready: false, status: 'starting' },
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        success: true,
        data: { ready: true, status: 'ready' },
      }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const runtimePromise = initializeRuntime();
    await vi.advanceTimersByTimeAsync(250);
    const runtime = await runtimePromise;

    expect(invokeMock).toHaveBeenCalledWith('start_backend');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/api/ready',
      expect.objectContaining({ method: 'GET' })
    );
    expect(runtime.isDesktop).toBe(true);
    expect(runtime.backendPid).toBe(4321);
  });
});
