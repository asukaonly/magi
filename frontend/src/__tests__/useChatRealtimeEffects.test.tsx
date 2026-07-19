import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createChatRealtimeResponseTracker,
  projectChatRealtimeEffectPlan,
} from '@/domain/chat/realtime';
import { MAX_RHYTHM_SEGMENT_COUNT } from '@/domain/chat/rhythm';
import {
  PENDING_HISTORY_RECONCILE_DELAY_MS,
  useChatRealtimeEffects,
} from '@/hooks/useChatRealtimeEffects';
import hookSource from '@/hooks/useChatRealtimeEffects.ts?raw';
import type { RealtimeMessage } from '@/realtime/provider';

const ACTIVE_RECONCILIATION = { resolved: false } as const;
const RESOLVED_RECONCILIATION = { resolved: true } as const;

const { subscribeMock } = vi.hoisted(() => ({
  subscribeMock: vi.fn(),
}));

vi.mock('@/realtime/provider', () => ({
  useRealtime: () => ({
    subscribe: subscribeMock,
  }),
}));

describe('useChatRealtimeEffects', () => {
  let listener: ((message: RealtimeMessage) => void) | null;

  beforeEach(() => {
    listener = null;
    subscribeMock.mockReset();
    subscribeMock.mockImplementation((nextListener: (message: RealtimeMessage) => void) => {
      listener = nextListener;
      return vi.fn();
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps realtime event policy outside the subscription hook', () => {
    expect(hookSource).not.toContain('assistant_rhythm_segment');
    expect(hookSource).not.toContain('segment_index');
    expect(hookSource).not.toContain('segment_count');
  });

  it('keeps the pending turn locked until the final rhythm segment arrives', () => {
    const clearPendingResponseTurn = vi.fn();

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-rhythm' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn: vi.fn().mockResolvedValue(ACTIVE_RECONCILIATION),
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-rhythm',
        message_kind: 'assistant_rhythm_segment',
        message_payload: {
          rhythm: {
            segment_index: 0,
            segment_count: 2,
          },
        },
      },
    });

    expect(clearPendingResponseTurn).not.toHaveBeenCalled();

    listener?.({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-rhythm',
        message_kind: 'assistant_rhythm_segment',
        message_payload: {
          rhythm: {
            segment_index: 1,
            segment_count: 2,
          },
        },
      },
    });

    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-rhythm',
    });
  });

  it('clears the pending turn on ordinary final responses', () => {
    const clearPendingResponseTurn = vi.fn();

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-final' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn: vi.fn().mockResolvedValue(ACTIVE_RECONCILIATION),
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-final',
        message_kind: 'assistant_final',
      },
    });

    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-final',
    });
  });

  it('does not clear the pending turn for another session or turn', () => {
    const clearPendingResponseTurn = vi.fn();
    const reconcilePendingResponseTurn = vi.fn().mockResolvedValue(RESOLVED_RECONCILIATION);

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-1' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn,
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'agent_response',
      data: {
        session_id: 'session-2',
        turn_id: 'turn-1',
        message_kind: 'assistant_final',
      },
    });
    listener?.({
      event: 'turn_execution_control',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-2',
        state: 'completed',
      },
    });

    expect(clearPendingResponseTurn).not.toHaveBeenCalled();
    expect(reconcilePendingResponseTurn).not.toHaveBeenCalled();
  });

  it('does not clear on an explicitly non-final agent response', () => {
    const clearPendingResponseTurn = vi.fn();

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-1' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn: vi.fn().mockResolvedValue(ACTIVE_RECONCILIATION),
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-1',
        is_final: false,
      },
    });

    expect(clearPendingResponseTurn).not.toHaveBeenCalled();
  });

  it('clears the matching pending turn when a durable failure message is upserted', () => {
    const clearPendingResponseTurn = vi.fn();

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-failed' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn: vi.fn().mockResolvedValue(ACTIVE_RECONCILIATION),
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'chat_message_upserted',
      data: {
        session_id: 'session-1',
        message: {
          role: 'assistant',
          turn_id: 'turn-failed',
          message_kind: 'assistant_final',
        },
      },
    });

    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-failed',
    });
  });

  it('reconciles durable history before clearing on a completed control event', async () => {
    const clearPendingResponseTurn = vi.fn();
    const reconcilePendingResponseTurn = vi.fn().mockResolvedValue(RESOLVED_RECONCILIATION);

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-rhythm' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn,
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'turn_execution_control',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-rhythm',
        state: 'completed',
      },
    });

    await waitFor(() => {
      expect(reconcilePendingResponseTurn).toHaveBeenCalledWith(
        'session-1',
        'turn-rhythm',
      );
    });
    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-rhythm',
    });
  });

  it('reconciles durable history before clearing on a failed control event', async () => {
    const clearPendingResponseTurn = vi.fn();
    const reconcilePendingResponseTurn = vi.fn().mockResolvedValue(RESOLVED_RECONCILIATION);

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-failed' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn,
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'turn_execution_control',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-failed',
        state: 'failed',
      },
    });

    await waitFor(() => {
      expect(reconcilePendingResponseTurn).toHaveBeenCalledWith(
        'session-1',
        'turn-failed',
      );
    });
    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-failed',
    });
  });

  it('recovers from a lost realtime notification through durable history', async () => {
    vi.useFakeTimers();
    const clearPendingResponseTurn = vi.fn();
    const settleTurnFromHistory = vi.fn();
    const reconcilePendingResponseTurn = vi.fn().mockResolvedValue({
      resolved: true,
      safeToCommitHistory: true,
      terminalRunState: 'cancelled',
    });

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-missed' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn,
      settleTurnFromHistory,
      clearPendingResponseTurn,
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PENDING_HISTORY_RECONCILE_DELAY_MS);
    });

    expect(reconcilePendingResponseTurn).toHaveBeenCalledWith(
      'session-1',
      'turn-missed',
    );
    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-missed',
    });
    expect(settleTurnFromHistory).toHaveBeenCalledWith(
      'session-1',
      'turn-missed',
      'cancelled',
    );
  });

  it('retries a non-terminal history check without unlocking early', async () => {
    vi.useFakeTimers();
    const clearPendingResponseTurn = vi.fn();
    const reconcilePendingResponseTurn = vi.fn()
      .mockResolvedValueOnce(ACTIVE_RECONCILIATION)
      .mockResolvedValueOnce(RESOLVED_RECONCILIATION);

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-running' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn,
      clearPendingResponseTurn,
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PENDING_HISTORY_RECONCILE_DELAY_MS);
    });
    expect(reconcilePendingResponseTurn).toHaveBeenCalledTimes(1);
    expect(clearPendingResponseTurn).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(reconcilePendingResponseTurn).toHaveBeenCalledTimes(2);
    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-running',
    });
  });

  it('honors the presentation deadline returned by history reconciliation', async () => {
    vi.useFakeTimers();
    const clearPendingResponseTurn = vi.fn();
    const reconcilePendingResponseTurn = vi.fn()
      .mockResolvedValueOnce({
        resolved: false,
        safeToCommitHistory: true,
        retryAfterMs: 10_000,
      })
      .mockResolvedValueOnce(RESOLVED_RECONCILIATION);

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      pendingResponseTurnsBySession: { 'session-1': 'turn-presenting' },
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      reconcilePendingResponseTurn,
      clearPendingResponseTurn,
    }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PENDING_HISTORY_RECONCILE_DELAY_MS);
    });
    expect(reconcilePendingResponseTurn).toHaveBeenCalledTimes(1);
    expect(clearPendingResponseTurn).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9_999);
    });
    expect(reconcilePendingResponseTurn).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(reconcilePendingResponseTurn).toHaveBeenCalledTimes(2);
    expect(clearPendingResponseTurn).toHaveBeenCalledWith({
      sessionId: 'session-1',
      turnId: 'turn-presenting',
    });
  });
});

describe('projectChatRealtimeEffectPlan', () => {
  it('requires the full rhythm set outside the React hook', () => {
    const tracker = createChatRealtimeResponseTracker();
    const finalSegmentFirst = projectChatRealtimeEffectPlan({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-rhythm',
        message_id: 'message-rhythm-2',
        message_kind: 'assistant_rhythm_segment',
        message_payload: { rhythm: { segment_index: 1, segment_count: 2 } },
      },
    }, {
      allowInterjection: false,
      turnsBySession: { 'session-1': 'turn-rhythm' },
    }, tracker);
    const firstSegment = projectChatRealtimeEffectPlan({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-rhythm',
        message_id: 'message-rhythm-1',
        message_kind: 'assistant_rhythm_segment',
        message_payload: { rhythm: { segment_index: 0, segment_count: 2 } },
      },
    }, {
      allowInterjection: false,
      turnsBySession: { 'session-1': 'turn-rhythm' },
    }, tracker);
    const duplicateFinalSegment = projectChatRealtimeEffectPlan({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-rhythm',
        message_id: 'message-rhythm-2',
        message_kind: 'assistant_rhythm_segment',
        message_payload: { rhythm: { segment_index: 1, segment_count: 2 } },
      },
    }, {
      allowInterjection: false,
      turnsBySession: { 'session-1': 'turn-rhythm' },
    }, tracker);

    expect(finalSegmentFirst.clearPendingResponseTurn).toBeUndefined();
    expect(firstSegment.clearPendingResponseTurn).toEqual({
      sessionId: 'session-1',
      turnId: 'turn-rhythm',
    });
    expect(duplicateFinalSegment.clearPendingResponseTurn).toBeUndefined();
  });

  it.each([
    { rhythm: null, label: 'missing metadata' },
    {
      rhythm: { segment_index: 1, segment_count: MAX_RHYTHM_SEGMENT_COUNT + 1 },
      label: 'unbounded count',
    },
    {
      rhythm: { segment_index: true, segment_count: 2 },
      label: 'boolean index',
    },
    {
      rhythm: { segment_index: '1.0', segment_count: 2 },
      label: 'non-canonical index',
    },
  ])('fails closed for $label', ({ rhythm }) => {
    const tracker = createChatRealtimeResponseTracker();
    const result = projectChatRealtimeEffectPlan({
      event: 'agent_response',
      data: {
        session_id: 'session-1',
        turn_id: 'turn-invalid-rhythm',
        message_kind: 'assistant_rhythm_segment',
        message_payload: rhythm ? { rhythm } : {},
      },
    }, {
      allowInterjection: false,
      turnsBySession: { 'session-1': 'turn-invalid-rhythm' },
    }, tracker);

    expect(result.clearPendingResponseTurn).toBeUndefined();
  });
});
