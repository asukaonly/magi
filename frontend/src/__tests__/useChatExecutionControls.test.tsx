import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { messagesApi } from '@/api';
import { useChatExecutionControls } from '@/hooks/useChatExecutionControls';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock('@/api', () => ({
  messagesApi: {
    cancelRun: vi.fn(),
    detachRun: vi.fn(),
  },
}));

describe('useChatExecutionControls', () => {
  beforeEach(() => {
    vi.mocked(messagesApi.cancelRun).mockReset();
    vi.mocked(messagesApi.detachRun).mockReset();
  });

  it('blocks duplicate stop requests and stays cancelling until a terminal event', async () => {
    let resolveRequest: ((
      value: Awaited<ReturnType<typeof messagesApi.cancelRun>>,
    ) => void) | null = null;
    vi.mocked(messagesApi.cancelRun).mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }) as ReturnType<typeof messagesApi.cancelRun>);
    const { result } = renderHook(() => useChatExecutionControls({
      currentSessionId: 'session-1',
    }));

    let firstRequest: Promise<unknown> | null = null;
    let duplicateRequest: Promise<unknown> | null = null;
    act(() => {
      firstRequest = result.current.requestRunCancel('turn-1');
      duplicateRequest = result.current.requestRunCancel('turn-1');
    });

    expect(messagesApi.cancelRun).toHaveBeenCalledTimes(1);
    expect(await duplicateRequest).toBe('ignored');
    expect(result.current.cancellingTurnIds).toEqual(['turn-1']);

    await act(async () => {
      resolveRequest?.({
        success: true,
        message: 'cancelling',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          run_id: 'run-1',
          status: 'cancelling',
        },
      });
      await firstRequest;
    });

    expect(result.current.cancellingTurnIds).toEqual(['turn-1']);

    act(() => {
      result.current.handleTurnExecutionControlEvent({
        session_id: 'session-1',
        turn_id: 'turn-1',
        state: 'cancelled',
      });
    });

    expect(result.current.cancellingTurnIds).toEqual([]);
  });

  it('settles normally when the backend confirms there is no active run', async () => {
    vi.mocked(messagesApi.cancelRun).mockResolvedValue({
      success: false,
      message: 'no active run',
      data: {
        user_id: 'local_user',
        session_id: 'session-1',
      },
    });
    const { result } = renderHook(() => useChatExecutionControls({
      currentSessionId: 'session-1',
    }));

    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.requestRunCancel('turn-stale');
    });

    expect(outcome).toBe('settled');
    expect(result.current.cancellingTurnIds).toEqual([]);
  });

  it('releases an exact pending cancellation when terminal history is reconciled', async () => {
    vi.mocked(messagesApi.cancelRun)
      .mockResolvedValueOnce({
        success: true,
        message: 'cancelling',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          run_id: 'run-1',
          status: 'cancelling',
        },
      })
      .mockResolvedValueOnce({
        success: true,
        message: 'cancelling again',
        data: {
          user_id: 'local_user',
          session_id: 'session-1',
          run_id: 'run-2',
          status: 'cancelling',
        },
      });
    const { result } = renderHook(() => useChatExecutionControls({
      currentSessionId: 'session-1',
    }));

    await act(async () => {
      expect(await result.current.requestRunCancel('turn-1')).toBe('pending');
    });
    expect(result.current.cancellingTurnIds).toEqual(['turn-1']);

    act(() => {
      result.current.settleTurnFromHistory(
        'session-1',
        'turn-1',
        'cancelled',
      );
    });

    expect(result.current.cancellingTurnIds).toEqual([]);
    expect(result.current.executionControlByTurnId['turn-1']?.state).toBe('cancelled');

    await act(async () => {
      expect(await result.current.requestRunCancel('turn-1')).toBe('pending');
    });
    expect(messagesApi.cancelRun).toHaveBeenCalledTimes(2);
  });
});
