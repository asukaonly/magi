import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useChatRealtimeEffects } from '@/hooks/useChatRealtimeEffects';
import type { RealtimeMessage } from '@/realtime/provider';

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

  it('keeps the pending turn locked until the final rhythm segment arrives', () => {
    const clearPendingResponseTurn = vi.fn();

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      turnActive: true,
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'agent_response',
      data: {
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

    expect(clearPendingResponseTurn).toHaveBeenCalledTimes(1);
  });

  it('clears the pending turn on ordinary final responses', () => {
    const clearPendingResponseTurn = vi.fn();

    renderHook(() => useChatRealtimeEffects({
      allowInterjection: false,
      turnActive: true,
      refreshVisibleTrace: vi.fn(),
      handleTurnExecutionControlEvent: vi.fn(),
      clearPendingResponseTurn,
    }));

    listener?.({
      event: 'agent_response',
      data: {
        turn_id: 'turn-final',
        message_kind: 'assistant_final',
      },
    });

    expect(clearPendingResponseTurn).toHaveBeenCalledTimes(1);
  });
});
