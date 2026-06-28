type ChatRealtimeEnvelope = {
  event?: string | null;
  type?: string | null;
  data?: any;
};

type PendingTurnState = {
  allowInterjection: boolean;
  turnActive: boolean;
};

export type ChatRealtimeEffectPlan = {
  refreshTraceTurnId?: string;
  turnExecutionControlPayload?: any;
  syncSession: boolean;
  clearPendingResponseTurn: boolean;
};

const EMPTY_PLAN: ChatRealtimeEffectPlan = {
  syncSession: false,
  clearPendingResponseTurn: false,
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

export const isTerminalAgentResponse = (payload: any): boolean => {
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

export const projectChatRealtimeEffectPlan = (
  envelope: ChatRealtimeEnvelope,
  pendingTurnState: PendingTurnState,
): ChatRealtimeEffectPlan => {
  const eventName = envelope.event || envelope.type;

  if (eventName === 'execution_trace_update' && envelope.data) {
    return {
      ...EMPTY_PLAN,
      refreshTraceTurnId: String(envelope.data?.turn_id || ''),
    };
  }

  if (eventName === 'turn_execution_control' && envelope.data) {
    return {
      ...EMPTY_PLAN,
      turnExecutionControlPayload: envelope.data,
    };
  }

  if (eventName !== 'agent_response' || !envelope.data) {
    return EMPTY_PLAN;
  }

  const payload = envelope.data;
  const messageKind = String(payload?.message_kind || '').trim();
  return {
    refreshTraceTurnId: String(payload?.turn_id || ''),
    syncSession: messageKind !== 'assistant_rhythm_segment',
    clearPendingResponseTurn: (
      pendingTurnState.turnActive
      && !pendingTurnState.allowInterjection
      && isTerminalAgentResponse(payload)
    ),
  };
};
