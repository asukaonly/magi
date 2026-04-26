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
    window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    refreshVisibleTrace(turnId);
    if (turnActive && !allowInterjection) {
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