import {
  normalizeHistoryMessages,
  normalizeTraceSummary,
  normalizeTurnUxPlan,
} from '@/domain/chat/state';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { useChatTraceStore } from '@/stores/chat-trace';
import { useConversationStore } from '@/stores/conversation-store';
import { useContextUsageStore } from '@/stores/context-usage';
import { useDelegationsStore } from '@/stores/delegations-store';
import type {
  DelegationLifecycle,
  RunEvent,
} from '@/api/modules/codeAgent';
import type { RealtimeStreamEvent } from './stream-events';
import { normalizeRealtimeStreamEvent } from './stream-events';

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
  const normalized = String(value || '').trim();
  return normalized || undefined;
};

export const applyRealtimeStoreProjection = (
  message: RealtimeStoreProjectionMessage,
  options: RealtimeStoreProjectionOptions = {},
): boolean => {
  const eventName = String(message.event || message.type || '').trim();
  const conversationStore = useConversationStore.getState();

  if (eventName === 'agent_response' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    const turnId = String(payload.turn_id || '').trim();
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

    if (sessionId) {
      conversationStore.receiveAgentResponse({
        sessionId,
        content: String(payload.content || ''),
        attachments: Array.isArray(payload.attachments)
          ? payload.attachments as any[]
          : undefined,
        timestamp,
        messageId: payload.message_id ? String(payload.message_id) : undefined,
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

  if (eventName === 'agent_response_chunk' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    const turnId = String(payload.turn_id || '').trim();
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

    const contentDelta = String(payload.content_delta || '');
    if (contentDelta) {
      conversationStore.appendStreamTextDelta({
        sessionId,
        turnId,
        personaId,
        textDelta: contentDelta,
      });
    }
    if (payload.is_final) {
      conversationStore.appendStreamTextFlush({
        sessionId,
        turnId,
        personaId,
      });
    }
    return Boolean(contentDelta) || Boolean(payload.is_final);
  }

  if (eventName === 'chat_message_upserted' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    const rawMessage = payload.message;
    if (sessionId && rawMessage && typeof rawMessage === 'object') {
      const normalizedMessage = normalizeHistoryMessages([rawMessage as any])[0];
      if (normalizedMessage) {
        conversationStore.upsertMessage(sessionId, normalizedMessage);
      }
    }
    if (payload.session_summary && typeof payload.session_summary === 'object') {
      conversationStore.upsertSession(payload.session_summary as any);
    }
    return true;
  }

  if (eventName === 'chat_message_hidden' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    const messageId = String(payload.message_id || '').trim();
    if (sessionId && messageId) {
      conversationStore.removeMessage(sessionId, messageId);
    }
    if (payload.session_summary && typeof payload.session_summary === 'object') {
      conversationStore.upsertSession(payload.session_summary as any);
    }
    return true;
  }

  if (eventName === 'turn_ux_plan' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    const turnId = String(payload.turn_id || '').trim();
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

  if (eventName === 'execution_trace_update' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    const turnId = String(payload.turn_id || '').trim();
    const summary = normalizeTraceSummary(payload.trace_summary);
    if (sessionId && turnId && summary) {
      useChatTraceStore.getState().upsertSummary(summary);
      conversationStore.upsertTraceSummary(sessionId, turnId, summary);
      return true;
    }
    return Boolean(sessionId && turnId);
  }

  if (eventName === 'context_usage' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sessionId = String(payload.session_id || conversationStore.currentSessionId || '').trim();
    if (sessionId && typeof payload.used_tokens === 'number' && typeof payload.window_size === 'number') {
      useContextUsageStore.getState().update(sessionId, {
        used_tokens: payload.used_tokens as number,
        window_size: payload.window_size as number,
        threshold: (payload.threshold as number) || 0,
      });
      return true;
    }
    return false;
  }

  if (eventName === 'background_task_state_changed' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    if (typeof payload.task_id === 'string' && typeof payload.status === 'string') {
      useBackgroundTaskStore.getState().upsert(payload as any);
      return true;
    }
    return false;
  }

  if (eventName === 'code_agent_delegation_event' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sid = typeof payload.session_id === 'string' ? payload.session_id : null;
    const did = typeof payload.delegation_id === 'string' ? payload.delegation_id : null;
    const event = (payload.event ?? null) as RunEvent | null;
    if (sid && did && event && typeof event === 'object' && typeof event.kind === 'string') {
      useDelegationsStore.getState().upsertEvent(sid, did, event);
      return true;
    }
    return false;
  }

  if (eventName === 'code_agent_delegation_state' && message.data && typeof message.data === 'object') {
    const payload = message.data as Record<string, unknown>;
    const sid = typeof payload.session_id === 'string' ? payload.session_id : null;
    const did = typeof payload.delegation_id === 'string' ? payload.delegation_id : null;
    const state = typeof payload.state === 'string' ? (payload.state as DelegationLifecycle) : null;
    const summary = (payload.summary ?? {}) as Record<string, unknown>;
    if (sid && did && state) {
      console.log('[store-projection] Received delegation state', { sid, did, state });
      useDelegationsStore.getState().upsertState(sid, did, state, summary);
      return true;
    }
    return false;
  }

  return false;
};