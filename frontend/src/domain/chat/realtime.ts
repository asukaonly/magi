import {
  readRhythmSegmentMeta,
} from '@/domain/chat/rhythm';
import {
  isTerminalRunState,
  type PendingResponseTurnIdentity,
  type PendingResponseTurnsBySession,
} from '@/domain/chat/turn-completion';

type ChatRealtimeEnvelope = {
  event?: string | null;
  type?: string | null;
  data?: any;
};

type PendingTurnState = {
  allowInterjection: boolean;
  turnsBySession: PendingResponseTurnsBySession;
};

export type ChatRealtimeEffectPlan = {
  refreshTraceTurnId?: string;
  turnExecutionControlPayload?: any;
  syncSession: boolean;
  clearPendingResponseTurn?: PendingResponseTurnIdentity;
  reconcilePendingResponseTurn?: PendingResponseTurnIdentity;
};

const EMPTY_PLAN: ChatRealtimeEffectPlan = {
  syncSession: false,
};

const readPayloadTurnIdentity = (
  payload: any,
): PendingResponseTurnIdentity | null => {
  const sessionId = String(
    payload?.session_id
    ?? payload?.sessionId
    ?? payload?.message?.session_id
    ?? payload?.message?.sessionId
    ?? '',
  ).trim();
  const turnId = String(
    payload?.turn_id
    ?? payload?.turnId
    ?? payload?.message?.turn_id
    ?? payload?.message?.turnId
    ?? '',
  ).trim();
  return sessionId && turnId ? { sessionId, turnId } : null;
};

const matchesPendingTurn = (
  payload: any,
  pendingTurnState: PendingTurnState,
): PendingResponseTurnIdentity | null => {
  if (pendingTurnState.allowInterjection) {
    return null;
  }
  const identity = readPayloadTurnIdentity(payload);
  if (!identity) {
    return null;
  }
  const pendingTurnId = String(
    pendingTurnState.turnsBySession[identity.sessionId] || '',
  ).trim();
  if (!pendingTurnId || identity.turnId !== pendingTurnId) {
    return null;
  }
  return identity;
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

type TrackedRhythmTurn = {
  segmentCount: number;
  segmentIds: Map<number, string>;
  invalid: boolean;
  completed: boolean;
};

export type ChatRealtimeResponseTracker = {
  observeRhythm: (payload: any) => boolean;
  reset: (identity?: PendingResponseTurnIdentity) => void;
};

const MAX_TRACKED_RHYTHM_TURNS = 32;

export const createChatRealtimeResponseTracker = (): ChatRealtimeResponseTracker => {
  const turns = new Map<string, TrackedRhythmTurn>();

  const reset = (identity?: PendingResponseTurnIdentity) => {
    if (identity?.sessionId && identity.turnId) {
      turns.delete(`${identity.sessionId}\u0000${identity.turnId}`);
      return;
    }
    turns.clear();
  };

  const observeRhythm = (payload: any): boolean => {
    const identity = readPayloadTurnIdentity(payload);
    if (!identity) {
      return false;
    }
    const turnKey = `${identity.sessionId}\u0000${identity.turnId}`;
    const meta = readRhythmSegmentMeta(getRhythmPayload(payload));
    if (!meta) {
      const existing = turns.get(turnKey);
      if (existing) {
        existing.invalid = true;
      } else {
        turns.set(turnKey, {
          segmentCount: 1,
          segmentIds: new Map(),
          invalid: true,
          completed: false,
        });
      }
      return false;
    }

    let state = turns.get(turnKey);
    if (!state) {
      if (turns.size >= MAX_TRACKED_RHYTHM_TURNS) {
        const oldestTurnId = turns.keys().next().value;
        if (typeof oldestTurnId === 'string') {
          turns.delete(oldestTurnId);
        }
      }
      state = {
        segmentCount: meta.segmentCount,
        segmentIds: new Map(),
        invalid: false,
        completed: false,
      };
      turns.set(turnKey, state);
    }
    if (state.completed) {
      return false;
    }
    if (state.segmentCount !== meta.segmentCount) {
      state.invalid = true;
      return false;
    }

    const messageId = String(payload?.message_id ?? payload?.messageId ?? '').trim();
    const previousMessageId = state.segmentIds.get(meta.segmentIndex);
    if (
      previousMessageId !== undefined
      && previousMessageId
      && messageId
      && previousMessageId !== messageId
    ) {
      state.invalid = true;
      return false;
    }
    if (previousMessageId === undefined) {
      state.segmentIds.set(meta.segmentIndex, messageId);
    } else if (!previousMessageId && messageId) {
      state.segmentIds.set(meta.segmentIndex, messageId);
    }
    if (state.invalid || state.segmentIds.size !== state.segmentCount) {
      return false;
    }
    for (let index = 0; index < state.segmentCount; index += 1) {
      if (!state.segmentIds.has(index)) {
        return false;
      }
    }
    state.completed = true;
    return true;
  };

  return { observeRhythm, reset };
};

export const isTerminalAgentResponse = (
  payload: any,
  responseTracker?: ChatRealtimeResponseTracker,
): boolean => {
  if (payload?.is_final === false || payload?.isFinal === false) {
    return false;
  }
  const messageKind = String(payload?.message_kind || '').trim();
  if (messageKind !== 'assistant_rhythm_segment') {
    const identity = readPayloadTurnIdentity(payload);
    if (identity) {
      responseTracker?.reset(identity);
    }
    return true;
  }
  return responseTracker?.observeRhythm(payload) ?? false;
};

export const projectChatRealtimeEffectPlan = (
  envelope: ChatRealtimeEnvelope,
  pendingTurnState: PendingTurnState,
  responseTracker?: ChatRealtimeResponseTracker,
): ChatRealtimeEffectPlan => {
  const eventName = envelope.event || envelope.type;

  if (eventName === 'execution_trace_update' && envelope.data) {
    return {
      ...EMPTY_PLAN,
      refreshTraceTurnId: String(envelope.data?.turn_id || ''),
    };
  }

  if (eventName === 'turn_execution_control' && envelope.data) {
    const state = String(envelope.data?.state || '').trim().toLowerCase();
    const matchesPending = matchesPendingTurn(envelope.data, pendingTurnState);
    const terminal = isTerminalRunState(state);
    return {
      ...EMPTY_PLAN,
      turnExecutionControlPayload: envelope.data,
      reconcilePendingResponseTurn: (
        matchesPending && terminal
          ? matchesPending
          : undefined
      ),
    };
  }

  if (eventName === 'chat_message_upserted' && envelope.data) {
    const message = envelope.data?.message;
    const messageKind = String(message?.message_kind ?? message?.messageKind ?? '').trim();
    const role = String(message?.role || '').trim();
    return {
      ...EMPTY_PLAN,
      clearPendingResponseTurn: (
        role === 'assistant' && messageKind === 'assistant_final'
          ? matchesPendingTurn(envelope.data, pendingTurnState) || undefined
          : undefined
      ),
    };
  }

  if (eventName !== 'agent_response' || !envelope.data) {
    return EMPTY_PLAN;
  }

  const payload = envelope.data;
  const messageKind = String(payload?.message_kind || '').trim();
  const matchesPending = matchesPendingTurn(payload, pendingTurnState);
  return {
    refreshTraceTurnId: String(payload?.turn_id || ''),
    syncSession: messageKind !== 'assistant_rhythm_segment',
    clearPendingResponseTurn: (
      matchesPending
      && isTerminalAgentResponse(payload, responseTracker)
        ? matchesPending
        : undefined
    ),
  };
};
