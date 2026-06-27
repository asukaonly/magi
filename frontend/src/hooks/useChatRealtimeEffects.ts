import { useCallback, useEffect } from 'react';
import { APP_EVENTS } from '@/constants/events';
import { useRealtime, type RealtimeMessage as WSMessage } from '@/realtime/provider';

type UseChatRealtimeEffectsOptions = {
  allowInterjection: boolean;
  turnActive: boolean;
  refreshVisibleTrace: (turnId: string) => void;
  handleTurnExecutionControlEvent: (payload: any) => void;
  clearPendingResponseTurn: () => void;
};

const getRhythmPayload = (payload: any): Record<string, unknown> | null => {
  const candidates = [
    payload?.message_payload?.rhythm,
    payload?.payload?.rhythm,
    payload?.rhythm,
  ];
  const match = candidates.find((candidate) => candidate && typeof candidate === 'object');
  return match ? match as Record<string, unknown> : null;
};

const isFinalResponseForPendingTurn = (payload: any): boolean => {
  const messageKind = String(payload?.message_kind || '').trim();
  if (messageKind !== 'assistant_rhythm_segment') {
    return true;
  }
  const rhythm = getRhythmPayload(payload);
  if (!rhythm) {
    return true;
  }
  const segmentIndex = Number(rhythm.segment_index ?? rhythm.segmentIndex);
  const segmentCount = Number(rhythm.segment_count ?? rhythm.segmentCount);
  if (!Number.isInteger(segmentIndex) || !Number.isInteger(segmentCount) || segmentCount < 1) {
    return true;
  }
  return segmentIndex >= segmentCount - 1;
};

export function useChatRealtimeEffects({
  allowInterjection,
  turnActive,
  refreshVisibleTrace,
  handleTurnExecutionControlEvent,
  clearPendingResponseTurn,
}: UseChatRealtimeEffectsOptions) {
  const { subscribe } = useRealtime();

  const handleAgentResponseEvent = useCallback((payload: any) => {
    const turnId = String(payload?.turn_id || '').trim();
    const messageKind = String(payload?.message_kind || '').trim();
    if (messageKind !== 'assistant_rhythm_segment') {
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    }
    refreshVisibleTrace(turnId);
    if (turnActive && !allowInterjection && isFinalResponseForPendingTurn(payload)) {
      clearPendingResponseTurn();
    }
  }, [allowInterjection, clearPendingResponseTurn, refreshVisibleTrace, turnActive]);

  const handleRealtimeEvent = useCallback((data: WSMessage) => {
    const eventName = data.event || data.type;

    if (eventName === 'execution_trace_update' && data.data) {
      refreshVisibleTrace(String(data.data?.turn_id || ''));
      return;
    }

    if (eventName === 'turn_execution_control' && data.data) {
      handleTurnExecutionControlEvent(data.data);
      return;
    }

    if (eventName === 'agent_response' && data.data) {
      handleAgentResponseEvent(data.data);
    }
  }, [handleAgentResponseEvent, handleTurnExecutionControlEvent, refreshVisibleTrace]);

  useEffect(() => subscribe(handleRealtimeEvent), [handleRealtimeEvent, subscribe]);
}
