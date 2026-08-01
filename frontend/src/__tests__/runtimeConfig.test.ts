import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// vi.hoisted because vi.mock factories are hoisted above the const
// declaration; runtime/config now statically imports @tauri-apps/api/core,
// so the mock factory runs during this file's module-evaluation and would
// otherwise hit a TDZ on invokeMock.
const { invokeMock } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: invokeMock,
}));

import {
  initializeRuntime,
  normalizeApiBaseUrl,
  normalizeConnectableUrl,
  readBackendStartupDiagnostics,
  resetRuntimeInitialization,
  restartRuntimeAfterFullDataClear,
} from '@/runtime/config';

describe('runtime config URL normalization', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    invokeMock.mockReset();
    resetRuntimeInitialization();
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

  it('returns no startup diagnostics outside the Tauri desktop runtime', async () => {
    await expect(readBackendStartupDiagnostics()).resolves.toBeNull();
    expect(invokeMock).not.toHaveBeenCalled();
  });

  it('reads backend startup diagnostics from the desktop shell', async () => {
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    invokeMock.mockResolvedValue({
      logPath: 'C:\\Users\\asuka\\.magi\\logs\\backend-dev-hot.log',
      logExcerpt: 'Traceback: demo failure',
    });

    await expect(readBackendStartupDiagnostics()).resolves.toEqual({
      logPath: 'C:\\Users\\asuka\\.magi\\logs\\backend-dev-hot.log',
      logExcerpt: 'Traceback: demo failure',
    });
    expect(invokeMock).toHaveBeenCalledWith('read_backend_startup_diagnostics');
  });

  it('rejects initialization outside the Tauri desktop runtime', async () => {
    await expect(initializeRuntime()).rejects.toThrow('Desktop runtime requires Tauri');
    expect(invokeMock).not.toHaveBeenCalled();
  });

  it('waits for the backend ready probe after starting the desktop sidecar', async () => {
    vi.useFakeTimers();
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'start_backend') {
        return {
          ok: true,
          baseUrl: 'http://127.0.0.1:8000/api',
          sessionToken: 'token-1',
          apiPid: 4321,
          runtimeWorkerPid: 5678,
        };
      }

      if (command === 'poll_backend_startup') {
        return {
          ready: true,
          phase: 'ready',
        };
      }

      throw new Error(`Unexpected invoke command: ${command}`);
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        success: true,
        data: { ok: true },
      }), { status: 200 })
    );
    vi.stubGlobal('fetch', fetchMock);

    const runtimePromise = initializeRuntime();
    await vi.runAllTimersAsync();
    const runtime = await runtimePromise;

    expect(invokeMock).toHaveBeenCalledWith('start_backend');
    expect(invokeMock).toHaveBeenCalledWith('poll_backend_startup');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'http://127.0.0.1:8000/api/health',
      expect.objectContaining({ method: 'GET' })
    );
    expect(runtime.isDesktop).toBe(true);
    expect(runtime.apiPid).toBe(4321);
    expect(runtime.runtimeWorkerPid).toBe(5678);
    expect('__MAGI_RUNTIME__' in window).toBe(false);
  });

  it('stops and starts the backend exactly once after a recovered clear', async () => {
    vi.useFakeTimers();
    (window as Window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    let startCount = 0;
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'stop_backend') {
        return { ok: true };
      }
      if (command === 'start_backend') {
        startCount += 1;
        return {
          ok: true,
          baseUrl: `http://127.0.0.1:${8000 + startCount}/api`,
          sessionToken: `token-${startCount}`,
          apiPid: 4000 + startCount,
          runtimeWorkerPid: 5000 + startCount,
        };
      }
      if (command === 'poll_backend_startup') {
        return { ready: true, phase: 'ready' };
      }
      throw new Error(`Unexpected invoke command: ${command}`);
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })));

    const firstStart = initializeRuntime();
    await vi.runAllTimersAsync();
    await firstStart;

    const restart = restartRuntimeAfterFullDataClear();
    await vi.runAllTimersAsync();
    const runtime = await restart;

    expect(invokeMock.mock.calls.filter(([command]) => command === 'stop_backend')).toHaveLength(1);
    expect(invokeMock.mock.calls.filter(([command]) => command === 'start_backend')).toHaveLength(2);
    expect(runtime.apiBaseUrl).toBe('http://127.0.0.1:8002/api');
    expect(runtime.sessionToken).toBe('token-2');
  });
});
