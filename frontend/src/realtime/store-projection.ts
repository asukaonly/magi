import { isDelegateResult } from '@/api/code-agent-contract';
import { agentResponseSchema, contextUsageSchema, parseChatMessage, parseChatSession, parseBackgroundTask, validateRunEvent, delegationStateSchema } from '@/api/event-contract';
import { isRecord } from '@/utils/value-guards';
import {
  normalizeHistoryMessages,
  normalizeTraceSummary,
  normalizeTurnUxPlan,
} from '@/domain/chat/state';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { useNotificationStore } from '@/stores/notifications';
import { useChatTraceStore } from '@/stores/chat-trace';
import { useConversationStore } from '@/stores/conversation-store';
import { useContextUsageStore } from '@/stores/context-usage';
import { useDelegationsStore } from '@/stores/delegations-store';
import type { RealtimeStreamEvent } from './stream-events';
import { normalizeRealtimeStreamEvent } from './stream-events';
import {
  canApplyRealtimeChatProjection,
  isRealtimeChatSessionProjectionAllowed,
} from './chat-projection-retirement';

export interface RealtimeStoreProjectionMessage {
  type?: string;
  data?: unknown;
  event?: string;
  streamEvent?: RealtimeStreamEvent | null;
}

export interface RealtimeStoreProjectionOptions {
  pendingLabel?: string;
}

const normalizeOptionalString = (value: unknown): string | undefined => {
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized || undefined;
};

export const applyRealtimeStoreProjection = (
  message: RealtimeStoreProjectionMessage,
  options: RealtimeStoreProjectionOptions = {},
): boolean => {
  const eventName = String(message.event || message.type || '').trim();
  const conversationStore = useConversationStore.getState();
  if (!canApplyRealtimeChatProjection(eventName, message.data)) {
    return false;
  }

  if (eventName === 'agent_response' && isRecord(message.data)) {
    const parsed = agentResponseSchema.safeParse(message.data);
    if (!parsed.success) return false;
    const payload = parsed.data;
    const sessionId = normalizeOptionalString(payload.session_id) || '';
    const turnId = normalizeOptionalString(payload.turn_id) || '';
    const personaId = normalizeOptionalString(payload.persona_id);
    const timestamp = normalizeChatTimestamp(payload.timestamp);
    const summary = normalizeTraceSummary(payload.trace_summary);
    const uxPlan = normalizeTurnUxPlan(payload.ux_plan);

    const projectTraceSummary = () => {
      if (!summary) {
        return false;
      }
      useChatTraceStore.getState().upsertSummary(summary);
      if (sessionId) {
        conversationStore.upsertTraceSummary(sessionId, summary.turnId, summary);
      }
      return true;
    };

    if (uxPlan?.assistantSurfaceMode === 'none') {
      let projected = false;
      if (sessionId && turnId) {
        conversationStore.applyTurnUxPlan({
          sessionId,
          turnId,
          uxPlan,
          messageId: payload.message_id ? String(payload.message_id) : undefined,
          messageKind: payload.message_kind ? String(payload.message_kind) : null,
          timestamp,
        });
        projected = true;
      }
      return projectTraceSummary() || projected;
    }

    const messageId = payload.message_id ? String(payload.message_id) : undefined;

    // P3 Step 4: project unconditionally on ``session_id``. The Phase-G+1
    // convergence (Steps 2-3) made ``ChatSseChannel.deliver`` the sole writer of
    // ``agent_response``, carrying the full payload (turn_id/message_id/
    // trace_summary/ux_plan/…) for non-streamed turns; streamed turns emit no
    // ``agent_response`` at all (they finalize via ``chat_message_upserted``).
    // The former lossy-channel-delivery skip — which guarded against a
    // turn_id-less channel emission inserting a ghost bubble — is therefore
    // obsolete: real payloads always carry turn_id, so ``receiveAgentResponse``
    // replaces the matching bubble cleanly instead of inserting a duplicate.
    if (sessionId) {
      conversationStore.receiveAgentResponse({
        sessionId,
        content: String(payload.content || ''),
        attachments: payload.attachments,
        timestamp,
        messageId,
        messageKind: payload.message_kind ? String(payload.message_kind) : null,
        personaId,
        turnId: turnId || undefined,
        traceSummary: summary,
        traceAvailable: Boolean(payload.trace_available || summary?.traceAvailable),
        uxPlan,
        payload:
          payload.message_payload && typeof payload.message_payload === 'object'
            ? payload.message_payload as Record<string, unknown>
            : null,
      });
    }

    projectTraceSummary();
    return true;
  }

  if (eventName === 'agent_response_chunk' && isRecord(message.data)) {
    const payload = message.data;
    const sessionId = normalizeOptionalString(payload.session_id) || '';
    const turnId = normalizeOptionalString(payload.turn_id) || '';
    const personaId = normalizeOptionalString(payload.persona_id);
    const streamEvent = message.streamEvent ?? normalizeRealtimeStreamEvent(payload);

    if (!sessionId || !turnId) {
      return false;
    }

    if (
      streamEvent
      && ['tool_call_start', 'tool_call_args', 'tool_call_end'].includes(streamEvent.kind)
    ) {
      conversationStore.appendStreamToolCall({
        sessionId,
        turnId,
        personaId,
        toolCallId: streamEvent.toolCallId,
        toolName: streamEvent.toolName,
        toolArgsDelta: streamEvent.toolArgsDelta,
        toolArguments: streamEvent.toolArguments,
        status: streamEvent.kind === 'tool_call_end' ? 'completed' : 'running',
      });
      return true;
    }

    if (streamEvent?.kind === 'text_delta' && streamEvent.text) {
      conversationStore.appendStreamTextDelta({
        sessionId,
        turnId,
        personaId,
        textDelta: streamEvent.text,
      });
      return true;
    }

    if (streamEvent?.kind === 'text_flush') {
      conversationStore.appendStreamTextFlush({
        sessionId,
        turnId,
        personaId,
      });
      return true;
    }

    if (streamEvent?.kind === 'text_reset') {
      conversationStore.appendStreamTextReset({
        sessionId,
        turnId,
        personaId,
      });
      return true;
    }

    if (streamEvent?.kind === 'reasoning_delta' && streamEvent.text) {
      conversationStore.appendStreamReasoningDelta({
        sessionId,
        turnId,
        personaId,
        source: streamEvent.source || 'unknown',
        stepLabel: streamEvent.stepLabel,
        textDelta: streamEvent.text,
      });
      return true;
    }

    if (streamEvent?.kind === 'status_update' && streamEvent.text) {
      conversationStore.appendStreamStatusUpdate({
        sessionId,
        turnId,
        personaId,
        source: streamEvent.source || 'assistant',
        stepLabel: streamEvent.stepLabel,
        content: streamEvent.text,
      });
      return true;
    }

    if (payload.is_final === true) {
      conversationStore.appendStreamTextFlush({ sessionId, turnId, personaId });
      return true;
    }
    return streamEvent !== null;
  }

  if (eventName === 'chat_message_upserted' && isRecord(message.data)) {
    const payload = message.data;
    const sessionId = normalizeOptionalString(payload.session_id) || '';
    if (!sessionId) return false;
    try {
      const rawMessage = parseChatMessage(payload.message);
      const session = payload.session_summary == null ? null : parseChatSession(payload.session_summary);
      if (session && session.session_id !== sessionId) return false;
      const normalizedMessage = normalizeHistoryMessages([rawMessage])[0];
      if (!normalizedMessage) return false;
      conversationStore.upsertMessage(sessionId, normalizedMessage);
      if (session && isRealtimeChatSessionProjectionAllowed(sessionId)) conversationStore.upsertSession(session);
      return true;
    } catch {
      return false;
    }
  }

  if (eventName === 'chat_message_hidden' && isRecord(message.data)) {
    const payload = message.data;
    const sessionId = normalizeOptionalString(payload.session_id);
    const messageId = normalizeOptionalString(payload.message_id);
    if (!sessionId || !messageId) return false;
    try {
      const session = payload.session_summary == null ? null : parseChatSession(payload.session_summary);
      if (session && session.session_id !== sessionId) return false;
      conversationStore.removeMessage(sessionId, messageId);
      if (session && isRealtimeChatSessionProjectionAllowed(sessionId)) conversationStore.upsertSession(session);
      return true;
    } catch {
      return false;
    }
  }

  if (eventName === 'turn_ux_plan' && isRecord(message.data)) {
    const payload = message.data;
    const sessionId = normalizeOptionalString(payload.session_id) || '';
    const turnId = normalizeOptionalString(payload.turn_id) || '';
    const uxPlan = normalizeTurnUxPlan(payload.ux_plan);

    if (!sessionId || !turnId || !uxPlan) {
      return false;
    }

    conversationStore.applyTurnUxPlan({
      sessionId,
      turnId,
      uxPlan,
      pendingLabel: options.pendingLabel || 'chat.trace.pending',
      messageId: payload.message_id ? String(payload.message_id) : undefined,
      messageKind: payload.message_kind ? String(payload.message_kind) : null,
      timestamp: normalizeChatTimestamp(payload.timestamp),
    });
    return true;
  }

  if (eventName === 'execution_trace_update' && isRecord(message.data)) {
    const payload = message.data;
    const sessionId = normalizeOptionalString(payload.session_id) || '';
    const turnId = normalizeOptionalString(payload.turn_id) || '';
    const summary = normalizeTraceSummary(payload.trace_summary);
    if (sessionId && turnId && summary) {
      useChatTraceStore.getState().upsertSummary(summary);
      conversationStore.upsertTraceSummary(sessionId, turnId, summary);
      return true;
    }
    return Boolean(sessionId && turnId);
  }

  if (eventName === 'context_usage' && isRecord(message.data)) {
    const parsed = contextUsageSchema.safeParse(message.data);
    if (!parsed.success) return false;
    const payload = parsed.data;
    useContextUsageStore.getState().update(payload.session_id, {
      ...payload, turn_id: payload.turn_id ?? null, updated_at_ms: payload.updated_at_ms ?? undefined,
    });
    return true;
  }

  if (eventName === 'background_task_state_changed') {
    try {
      return useBackgroundTaskStore.getState().upsert(parseBackgroundTask(message.data));
    } catch {
      return false;
    }
  }

  if (eventName === 'user_notification_added') {
    void useNotificationStore.getState().refresh();
    return true;
  }

  if (eventName === 'code_agent_delegation_event' && isRecord(message.data)) {
    const payload = message.data;
    const sid = typeof payload.session_id === 'string' ? payload.session_id : null;
    const tid = typeof payload.turn_id === 'string' ? payload.turn_id : null;
    const did = typeof payload.delegation_id === 'string' ? payload.delegation_id : null;
    const event = payload.event;
    if (sid && tid && did && validateRunEvent(event)) {
      useDelegationsStore.getState().upsertEvent(sid, did, tid, event);
      return true;
    }
    return false;
  }

  if (eventName === 'code_agent_delegation_state' && isRecord(message.data)) {
    const payload = message.data;
    const sid = typeof payload.session_id === 'string' ? payload.session_id : null;
    const tid = typeof payload.turn_id === 'string' ? payload.turn_id : null;
    const did = typeof payload.delegation_id === 'string' ? payload.delegation_id : null;
    const state = delegationStateSchema.safeParse(payload.state);
    const summary = payload.summary ?? {};
    if (sid && tid && did && state.success && isRecord(summary)) {
      const terminal = state.data === 'finished' || state.data === 'failed' || state.data === 'cancelled';
      const result = terminal && isDelegateResult(summary, did) ? summary : null;
      if (terminal && !result) return false;
      useDelegationsStore.getState().upsertState(sid, did, tid, state.data, result);
      return true;
    }
    return false;
  }

  return false;
};
