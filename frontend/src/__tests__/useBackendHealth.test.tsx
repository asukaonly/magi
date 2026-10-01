import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useBackendHealth } from '@/hooks/useBackendHealth';
import { useBackendHealthStore } from '@/stores/backend-health';

const { mockGet } = vi.hoisted(() => ({
  mockGet: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  apiClient: {
    get: mockGet,
  },
}));

function makeReadyPayload(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    data: {
      success: true,
      data: {
        ready: false,
        status: 'degraded',
        runtime_ready: false,
        runtime_status: 'starting',
        worker_ready: true,
        llm_ready: false,
        agent_runtime_ready: false,
        startup_state: 'starting',
        deferred_reason: null,
        ...overrides,
      },
    },
  };
}

describe('useBackendHealth', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockGet.mockReset();
    useBackendHealthStore.setState({
      status: 'healthy',
      runtimeStatus: null,
      startupState: null,
      deferredReason: null,
      llmReady: null,
      agentRuntimeReady: null,
      lastCheckedAt: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('keeps startup degradation hidden during the initial grace period', async () => {
    mockGet.mockResolvedValue(makeReadyPayload());

    renderHook(() => useBackendHealth());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_000);
    });

    expect(useBackendHealthStore.getState().status).toBe('healthy');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });

    expect(useBackendHealthStore.getState().status).toBe('degraded');
  });

  it('returns to healthy quickly after the runtime becomes ready', async () => {
    mockGet
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(makeReadyPayload())
      .mockResolvedValueOnce(
        makeReadyPayload({
          ready: true,
          status: 'ready',
          runtime_ready: true,
          runtime_status: 'ready',
          llm_ready: true,
          agent_runtime_ready: true,
          startup_state: 'ready',
        }),
      );

    renderHook(() => useBackendHealth());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(33_000);
    });

    expect(useBackendHealthStore.getState().status).toBe('degraded');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });

    expect(useBackendHealthStore.getState().status).toBe('healthy');
  });

  it('requires two failed probes and clears the warning on recovery', async () => {
    mockGet.mockResolvedValue(makeReadyPayload({
      runtime_status: 'probe_timeout', startup_state: 'probe_timeout',
      llm_ready: null, agent_runtime_ready: null,
    }));
    renderHook(() => useBackendHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(useBackendHealthStore.getState().status).toBe('healthy');
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    expect(useBackendHealthStore.getState()).toMatchObject({
      status: 'degraded', runtimeStatus: 'probe_timeout', llmReady: null,
    });
    mockGet.mockResolvedValue(makeReadyPayload({
      ready: true, status: 'ready', runtime_ready: true,
      runtime_status: 'ready', startup_state: 'ready',
    }));
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    expect(useBackendHealthStore.getState().status).toBe('healthy');
  });

  it.each([
    { success: true, data: { status: 'ready' } },
    { success: false, data: makeReadyPayload().data.data },
    { success: true, data: { ...makeReadyPayload().data.data, runtime_ready: 'true' } },
  ])('rejects invalid readiness without declaring the worker offline', async (payload) => {
    mockGet.mockImplementation((path: string) => Promise.resolve({
      data: path === '/health' ? { status: 'ok' } : payload,
    }));
    renderHook(() => useBackendHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(7_000); });
    expect(useBackendHealthStore.getState()).toMatchObject({
      status: 'degraded', runtimeStatus: 'probe_failed',
    });
  });

  it('reports offline only when gateway liveness also fails', async () => {
    mockGet.mockRejectedValue(new Error('Connection refused'));
    renderHook(() => useBackendHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(7_000); });
    expect(useBackendHealthStore.getState().status).toBe('offline');
  });

  it('ignores a readiness response after the polling owner unmounts', async () => {
    let resolveResponse!: (value: ReturnType<typeof makeReadyPayload>) => void;
    mockGet.mockReturnValue(new Promise((resolve) => { resolveResponse = resolve; }));
    const { unmount } = renderHook(() => useBackendHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    unmount();
    useBackendHealthStore.getState().setHealth('degraded', { runtimeStatus: 'recovering' });
    await act(async () => {
      resolveResponse(makeReadyPayload({ status: 'ready' }));
      await Promise.resolve();
    });
    expect(useBackendHealthStore.getState().runtimeStatus).toBe('recovering');
  });
});
