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
});