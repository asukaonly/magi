import type {
  ChatTimelineMessage,
  ReasoningTrace,
  RuntimeStatusTrace,
  ToolCallTrace,
} from '@/domain/chat/state';
import { insertTimelineMessageForTurn } from '@/stores/conversation-timeline';

export type StreamTextDeltaPayload = {
  turnId: string;
  personaId?: string | null;
  textDelta: string;
};

export type StreamTextFlushPayload = {
  turnId: string;
  personaId?: string | null;
};

export type StreamTextResetPayload = {
  turnId: string;
  personaId?: string | null;
};

export type StreamReasoningDeltaPayload = {
  turnId: string;
  source: string;
  stepLabel?: string | null;
  personaId?: string | null;
  textDelta: string;
};

export type StreamStatusUpdatePayload = {
  turnId: string;
  source: string;
  stepLabel?: string | null;
  personaId?: string | null;
  content: string;
};

export type StreamToolCallPayload = {
  turnId: string;
  toolCallId?: string | null;
  toolName?: string | null;
  toolArgsDelta?: string;
  toolArguments?: Record<string, unknown> | null;
  personaId?: string | null;
  status: 'running' | 'completed';
};

export type StreamMessageUpdate = {
  messages: ChatTimelineMessage[];
  changed: boolean;
  needsSession: boolean;
};

const appendReasoning = (
  prev: ReasoningTrace[] | undefined,
  source: string,
  stepLabel: string | null | undefined,
  textDelta: string,
): ReasoningTrace[] => {
  const list = prev ? [...prev] : [];
  const normalizedLabel = stepLabel ?? null;
  const lastIdx = list.length - 1;
  if (lastIdx >= 0) {
    const last = list[lastIdx];
    if (last.source === source && (last.stepLabel ?? null) === normalizedLabel) {
      list[lastIdx] = { ...last, content: last.content + textDelta };
      return list;
    }
  }
  list.push({ source, stepLabel: normalizedLabel, content: textDelta });
  return list;
};

const appendRuntimeStatus = (
  prev: RuntimeStatusTrace[] | undefined,
  source: string,
  stepLabel: string | null | undefined,
  content: string,
): RuntimeStatusTrace[] => {
  const normalizedContent = String(content || '').trim();
  if (!normalizedContent) {
    return prev ? [...prev] : [];
  }
  const list = prev ? [...prev] : [];
  const normalizedSource = String(source || '').trim() || 'assistant';
  const normalizedLabel = stepLabel ?? null;
  const last = list[list.length - 1];
  if (
    last
    && last.source === normalizedSource
    && (last.stepLabel ?? null) === normalizedLabel
    && last.content.trim() === normalizedContent
  ) {
    return list;
  }
  list.push({ source: normalizedSource, stepLabel: normalizedLabel, content: normalizedContent });
  return list;
};

const appendToolCall = (
  prev: ToolCallTrace[] | undefined,
  payload: StreamToolCallPayload,
): ToolCallTrace[] => {
  const list = prev ? [...prev] : [];
  const normalizedToolName = String(payload.toolName || '').trim() || 'Tool';
  const normalizedArgsDelta = typeof payload.toolArgsDelta === 'string' ? payload.toolArgsDelta : '';
  const nextArguments = payload.toolArguments ?? undefined;
  const index = list.findIndex((item) => {
    if (payload.toolCallId && item.toolCallId) {
      return item.toolCallId === payload.toolCallId;
    }
    return item.toolName === normalizedToolName;
  });

  if (index >= 0) {
    const current = list[index];
    list[index] = {
      ...current,
      toolCallId: payload.toolCallId ?? current.toolCallId,
      toolName: payload.toolName ? normalizedToolName : current.toolName,
      status: payload.status,
      toolArgsText: normalizedArgsDelta
        ? `${current.toolArgsText || ''}${normalizedArgsDelta}`
        : current.toolArgsText,
      toolArguments: nextArguments ?? current.toolArguments,
    };
    return list;
  }

  list.push({
    toolCallId: payload.toolCallId ?? null,
    toolName: normalizedToolName,
    status: payload.status,
    toolArgsText: normalizedArgsDelta || undefined,
    toolArguments: nextArguments ?? null,
  });
  return list;
};

const findStreamingAssistantIndex = (
  messages: ChatTimelineMessage[],
  turnId: string,
): number => {
  const existingIndex = messages.findIndex(
    (message) => message.role === 'assistant' && message.turnId === turnId && message.streaming,
  );
  if (existingIndex >= 0) {
    return existingIndex;
  }
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (
      candidate.role === 'assistant'
      && candidate.turnId === turnId
      && !candidate.messageId
    ) {
      return index;
    }
  }
  return -1;
};

const trimTrailingStreamNewlines = (content: string): string => (
  String(content || '').replace(/(?:\r?\n)+$/, '')
);

const buildStreamPlaceholder = (
  turnId: string,
  personaId: string | null | undefined,
  fields: Partial<ChatTimelineMessage> = {},
): ChatTimelineMessage => ({
  id: `stream_${turnId}`,
  role: 'assistant',
  kind: 'assistant',
  content: '',
  timestamp: Date.now(),
  turnId,
  personaId: personaId ?? null,
  streaming: true,
  ...fields,
});

const unchanged = (messages: ChatTimelineMessage[]): StreamMessageUpdate => ({
  messages,
  changed: false,
  needsSession: false,
});

export const applyStreamTextDelta = (
  previousMessages: ChatTimelineMessage[],
  payload: StreamTextDeltaPayload,
): StreamMessageUpdate => {
  const { turnId, personaId, textDelta } = payload;
  if (!turnId || !textDelta) {
    return unchanged(previousMessages);
  }
  const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
  if (existingIndex >= 0) {
    const existing = previousMessages[existingIndex];
    const nextMessages = [...previousMessages];
    nextMessages[existingIndex] = {
      ...existing,
      content: existing.content + textDelta,
      personaId: personaId ?? existing.personaId ?? null,
      streaming: true,
    };
    return { messages: nextMessages, changed: true, needsSession: false };
  }

  const streamingMessage = buildStreamPlaceholder(turnId, personaId, {
    content: textDelta,
  });
  return {
    messages: insertTimelineMessageForTurn(previousMessages, streamingMessage),
    changed: true,
    needsSession: true,
  };
};

export const applyStreamTextFlush = (
  previousMessages: ChatTimelineMessage[],
  payload: StreamTextFlushPayload,
): StreamMessageUpdate => {
  const { turnId, personaId } = payload;
  if (!turnId) {
    return unchanged(previousMessages);
  }
  const existingIndex = previousMessages.findIndex(
    (message) => message.role === 'assistant' && message.turnId === turnId && message.streaming,
  );
  if (existingIndex < 0) {
    return unchanged(previousMessages);
  }
  const existing = previousMessages[existingIndex];
  const nextMessages = [...previousMessages];
  nextMessages[existingIndex] = {
    ...existing,
    content: trimTrailingStreamNewlines(existing.content),
    personaId: personaId ?? existing.personaId ?? null,
    streaming: false,
  };
  return { messages: nextMessages, changed: true, needsSession: false };
};

export const applyStreamTextReset = (
  previousMessages: ChatTimelineMessage[],
  payload: StreamTextResetPayload,
): StreamMessageUpdate => {
  const { turnId, personaId } = payload;
  if (!turnId) {
    return unchanged(previousMessages);
  }
  const existingIndex = previousMessages.findIndex(
    (message) => message.role === 'assistant' && message.turnId === turnId && !message.messageId,
  );
  if (existingIndex < 0) {
    return unchanged(previousMessages);
  }
  const existing = previousMessages[existingIndex];
  const nextMessages = [...previousMessages];
  nextMessages[existingIndex] = {
    ...existing,
    content: '',
    personaId: personaId ?? existing.personaId ?? null,
    streaming: true,
  };
  return { messages: nextMessages, changed: true, needsSession: false };
};

export const applyStreamReasoningDelta = (
  previousMessages: ChatTimelineMessage[],
  payload: StreamReasoningDeltaPayload,
): StreamMessageUpdate => {
  const { turnId, source, stepLabel, personaId, textDelta } = payload;
  if (!turnId || !textDelta) {
    return unchanged(previousMessages);
  }
  const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
  if (existingIndex < 0) {
    const placeholder = buildStreamPlaceholder(turnId, personaId, {
      reasoning: appendReasoning([], source, stepLabel, textDelta),
    });
    return {
      messages: insertTimelineMessageForTurn(previousMessages, placeholder),
      changed: true,
      needsSession: true,
    };
  }

  const target = previousMessages[existingIndex];
  const nextMessages = [...previousMessages];
  nextMessages[existingIndex] = {
    ...target,
    personaId: personaId ?? target.personaId ?? null,
    reasoning: appendReasoning(target.reasoning, source, stepLabel, textDelta),
  };
  return { messages: nextMessages, changed: true, needsSession: false };
};

export const applyStreamStatusUpdate = (
  previousMessages: ChatTimelineMessage[],
  payload: StreamStatusUpdatePayload,
): StreamMessageUpdate => {
  const { turnId, source, stepLabel, personaId, content } = payload;
  if (!turnId || !String(content || '').trim()) {
    return unchanged(previousMessages);
  }
  const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
  if (existingIndex < 0) {
    const placeholder = buildStreamPlaceholder(turnId, personaId, {
      runtimeStatuses: appendRuntimeStatus([], source, stepLabel, content),
    });
    return {
      messages: insertTimelineMessageForTurn(previousMessages, placeholder),
      changed: true,
      needsSession: true,
    };
  }

  const target = previousMessages[existingIndex];
  const nextMessages = [...previousMessages];
  nextMessages[existingIndex] = {
    ...target,
    personaId: personaId ?? target.personaId ?? null,
    runtimeStatuses: appendRuntimeStatus(target.runtimeStatuses, source, stepLabel, content),
  };
  return { messages: nextMessages, changed: true, needsSession: false };
};

export const applyStreamToolCall = (
  previousMessages: ChatTimelineMessage[],
  payload: StreamToolCallPayload,
): StreamMessageUpdate => {
  const { turnId, personaId } = payload;
  if (!turnId) {
    return unchanged(previousMessages);
  }
  const existingIndex = findStreamingAssistantIndex(previousMessages, turnId);
  if (existingIndex < 0) {
    const placeholder = buildStreamPlaceholder(turnId, personaId, {
      toolCalls: appendToolCall([], payload),
    });
    return {
      messages: insertTimelineMessageForTurn(previousMessages, placeholder),
      changed: true,
      needsSession: true,
    };
  }

  const target = previousMessages[existingIndex];
  const nextMessages = [...previousMessages];
  nextMessages[existingIndex] = {
    ...target,
    personaId: personaId ?? target.personaId ?? null,
    toolCalls: appendToolCall(target.toolCalls, payload),
  };
  return { messages: nextMessages, changed: true, needsSession: false };
};
