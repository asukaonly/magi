import { useCallback, useEffect } from 'react';
import { APP_EVENTS } from '@/constants/events';
import { projectChatRealtimeEffectPlan } from '@/domain/chat/realtime';
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

  const handleRealtimeEvent = useCallback((data: WSMessage) => {
    const plan = projectChatRealtimeEffectPlan(data, {
      allowInterjection,
      turnActive,
    });

    if (plan.syncSession) {
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    }

    if (plan.refreshTraceTurnId !== undefined) {
      refreshVisibleTrace(plan.refreshTraceTurnId);
    }

    if (plan.turnExecutionControlPayload !== undefined) {
      handleTurnExecutionControlEvent(plan.turnExecutionControlPayload);
    }

    if (plan.clearPendingResponseTurn) {
      clearPendingResponseTurn();
    }
  }, [
    allowInterjection,
    clearPendingResponseTurn,
    handleTurnExecutionControlEvent,
    refreshVisibleTrace,
    turnActive,
  ]);

  useEffect(() => subscribe(handleRealtimeEvent), [handleRealtimeEvent, subscribe]);
}
