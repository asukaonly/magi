import { isRecord } from '@/utils/value-guards';
import { executionControlSchema, type ExecutionControlPayload } from '@/api/event-contract';
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
  data?: unknown;
};

type PendingTurnState = {
  allowInterjection: boolean;
  turnsBySession: PendingResponseTurnsBySession;
};

export type ChatRealtimeEffectPlan = {
  refreshTraceTurnId?: string;
  turnExecutionControlPayload?: ExecutionControlPayload;
  syncSession: boolean;
  clearPendingResponseTurn?: PendingResponseTurnIdentity;
  reconcilePendingResponseTurn?: PendingResponseTurnIdentity;
};

const EMPTY_PLAN: ChatRealtimeEffectPlan = {
  syncSession: false,
};

const readText = (value: unknown): string => typeof value === 'string' ? value.trim() : '';

const readPayloadTurnIdentity = (
  payload: unknown,
): PendingResponseTurnIdentity | null => {
  if (!isRecord(payload)) return null;
  const nested = isRecord(payload.message) ? payload.message : {};
  const sessionId = readText(payload.session_id ?? payload.sessionId ?? nested.session_id ?? nested.sessionId);
  const turnId = readText(payload.turn_id ?? payload.turnId ?? nested.turn_id ?? nested.turnId);
  return sessionId && turnId ? { sessionId, turnId } : null;
};


const matchesPendingTurn = (
  payload: unknown,
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

const getRhythmPayload = (payload: unknown): Record<string, unknown> | null => {
  if (!isRecord(payload)) return null;
  const messagePayload = isRecord(payload.message_payload) ? payload.message_payload : {};
  const innerPayload = isRecord(payload.payload) ? payload.payload : {};
  return [messagePayload.rhythm, innerPayload.rhythm, payload.rhythm].find(isRecord) ?? null;
};

type TrackedRhythmTurn = {
  segmentCount: number;
  segmentIds: Map<number, string>;
  invalid: boolean;
  completed: boolean;
};

export type ChatRealtimeResponseTracker = {
  observeRhythm: (payload: unknown) => boolean;
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

  const observeRhythm = (payload: unknown): boolean => {
    const identity = readPayloadTurnIdentity(payload);
    if (!identity) {
      return false;
    }
    if (!isRecord(payload)) return false;
    const turnKey = `${identity.sessionId}\u0000${identity.turnId}`;
    if (!turns.has(turnKey) && turns.size >= MAX_TRACKED_RHYTHM_TURNS) {
      const oldestKey = turns.keys().next().value;
      if (oldestKey !== undefined) turns.delete(oldestKey);
    }
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

    const messageId = readText(payload.message_id ?? payload.messageId);
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
  payload: unknown,
  responseTracker?: ChatRealtimeResponseTracker,
): boolean => {
  if (!isRecord(payload)) return false;
  if (payload.is_final !== undefined && typeof payload.is_final !== 'boolean') return false;
  if (payload?.is_final === false || payload?.isFinal === false) {
    return false;
  }
  const messageKind = readText(payload.message_kind);
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
  const payload = envelope.data;
  if (!isRecord(payload)) return EMPTY_PLAN;

  if (eventName === 'execution_trace_update' && payload) {
    return {
      ...EMPTY_PLAN,
      refreshTraceTurnId: readText(payload.turn_id),
    };
  }

  if (eventName === 'turn_execution_control' && payload) {
    const parsed = executionControlSchema.safeParse(payload);
    if (!parsed.success) return EMPTY_PLAN;
    const state = parsed.data.state.toLowerCase();
    const matchesPending = matchesPendingTurn(parsed.data, pendingTurnState);
    const terminal = isTerminalRunState(state);
    return {
      ...EMPTY_PLAN,
      turnExecutionControlPayload: parsed.data,
      reconcilePendingResponseTurn: (
        matchesPending && terminal
          ? matchesPending
          : undefined
      ),
    };
  }

  if (eventName === 'chat_message_upserted' && payload) {
    const message = isRecord(payload.message) ? payload.message : {};
    const messageKind = readText(message.message_kind ?? message.messageKind);
    const role = readText(message.role);
    return {
      ...EMPTY_PLAN,
      clearPendingResponseTurn: (
        role === 'assistant' && messageKind === 'assistant_final'
          ? matchesPendingTurn(payload, pendingTurnState) || undefined
          : undefined
      ),
    };
  }

  if (eventName !== 'agent_response' || !payload) {
    return EMPTY_PLAN;
  }

  const messageKind = readText(payload.message_kind);
  const matchesPending = matchesPendingTurn(payload, pendingTurnState);
  return {
    refreshTraceTurnId: readText(payload.turn_id),
    syncSession: messageKind !== 'assistant_rhythm_segment',
    clearPendingResponseTurn: (
      matchesPending
      && isTerminalAgentResponse(payload, responseTracker)
        ? matchesPending
        : undefined
    ),
  };
};
