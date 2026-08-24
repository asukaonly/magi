import type { ChatTimelineMessage } from '@/domain/chat/state';

const sortTimelineMessages = (messages: ChatTimelineMessage[]): ChatTimelineMessage[] => (
  [...messages].sort((left, right) => {
    const timestampDiff = Number(left.timestamp || 0) - Number(right.timestamp || 0);
    if (timestampDiff !== 0) {
      return timestampDiff;
    }
    if (left.role === right.role) {
      return 0;
    }
    return left.role === 'user' ? -1 : 1;
  })
);

export const insertTimelineMessageForTurn = (
  messages: ChatTimelineMessage[],
  incoming: ChatTimelineMessage,
): ChatTimelineMessage[] => {
  const turnId = String(incoming.turnId || '').trim();
  if (!turnId) {
    return sortTimelineMessages([...messages, incoming]);
  }

  let lastSameTurnIndex = -1;
  messages.forEach((message, index) => {
    if (String(message.turnId || '').trim() === turnId) {
      lastSameTurnIndex = index;
    }
  });

  if (lastSameTurnIndex < 0) {
    return sortTimelineMessages([...messages, incoming]);
  }

  const nextMessages = [...messages];
  nextMessages.splice(lastSameTurnIndex + 1, 0, incoming);
  return nextMessages;
};

export const canMergeTimelineMessage = (
  existing: ChatTimelineMessage,
  incoming: ChatTimelineMessage,
): boolean => {
  if (existing === incoming) {
    return true;
  }
  const existingMessageId = String(existing.messageId || '').trim();
  const incomingMessageId = String(incoming.messageId || '').trim();
  if (existingMessageId && incomingMessageId) {
    return existingMessageId === incomingMessageId;
  }

  const existingTurnId = String(existing.turnId || '').trim();
  const incomingTurnId = String(incoming.turnId || '').trim();
  if (!existingTurnId || !incomingTurnId || existingTurnId !== incomingTurnId || existing.role !== incoming.role) {
    return false;
  }

  const incomingIsAssistantTranscript = incoming.role === 'assistant' && incoming.kind === 'assistant';

  // A streaming assistant transcript is mergeable with later persisted
  // assistant transcript rows for the same turn, but not with control/status
  // rows such as plan_state.
  if (existing.streaming && incomingIsAssistantTranscript) {
    return true;
  }

  // A completed-streaming placeholder (no persisted messageId) is mergeable with
  // the persisted assistant transcript for the same turn so the duplicate is replaced.
  if (!existingMessageId && incomingMessageId && incomingIsAssistantTranscript) {
    return true;
  }

  if (existing.role === 'user') {
    return existing.kind === 'user' && incoming.kind === 'user';
  }

  const existingMessageKind = String(existing.messageKind || '').trim();
  const incomingMessageKind = String(incoming.messageKind || '').trim();
  return Boolean(existingMessageKind && incomingMessageKind && existingMessageKind === incomingMessageKind);
};

const mergeTimelineMessage = (
  existing: ChatTimelineMessage,
  incoming: ChatTimelineMessage,
): ChatTimelineMessage => ({
  ...existing,
  ...incoming,
  id: String(incoming.messageId || existing.messageId || incoming.id || existing.id),
  messageId: incoming.messageId ?? existing.messageId,
  messageKind: incoming.messageKind ?? existing.messageKind ?? null,
  turnId: incoming.turnId ?? existing.turnId,
  replyTo: incoming.replyTo ?? existing.replyTo ?? null,
  label: incoming.label ?? existing.label ?? null,
  reaction: incoming.reaction ?? existing.reaction ?? null,
  attachments: incoming.attachments ?? existing.attachments,
  traceDisplayMode: incoming.traceDisplayMode ?? existing.traceDisplayMode ?? null,
  allowTraceCollapse: typeof incoming.allowTraceCollapse === 'boolean'
    ? incoming.allowTraceCollapse
    : Boolean(existing.allowTraceCollapse),
  traceSummary: incoming.traceSummary ?? existing.traceSummary ?? null,
  traceAvailable: typeof incoming.traceAvailable === 'boolean'
    ? incoming.traceAvailable
    : Boolean(existing.traceAvailable),
  personaId: incoming.personaId ?? existing.personaId ?? null,
  runtimeStatuses: incoming.runtimeStatuses ?? existing.runtimeStatuses,
  reasoning: incoming.reasoning ?? existing.reasoning,
  toolCalls: incoming.toolCalls ?? existing.toolCalls,
});

export const upsertTimelineMessage = (
  messages: ChatTimelineMessage[],
  incoming: ChatTimelineMessage,
): ChatTimelineMessage[] => {
  const existingIndex = messages.findIndex((message) => canMergeTimelineMessage(message, incoming));
  if (existingIndex < 0) {
    return insertTimelineMessageForTurn(messages, incoming);
  }
  const nextMessages = [...messages];
  nextMessages[existingIndex] = mergeTimelineMessage(messages[existingIndex], incoming);
  return nextMessages;
};

export const mergeHistorySnapshot = (
  existingMessages: ChatTimelineMessage[],
  snapshotMessages: ChatTimelineMessage[],
): ChatTimelineMessage[] => {
  const mergedSnapshot = snapshotMessages.map((message) => {
    const existingMatch = existingMessages.find((current) => canMergeTimelineMessage(current, message));
    return existingMatch ? mergeTimelineMessage(existingMatch, message) : message;
  });

  const localPendingMessages = existingMessages.filter((message) => {
    const messageKind = String(message.messageKind || '').trim();
    const isLocalAskTranscript = messageKind === 'ask_request' || messageKind === 'ask_response';
    if (String(message.messageId || '').trim() && !isLocalAskTranscript) {
      return false;
    }
    return !snapshotMessages.some((snapshotMessage) => canMergeTimelineMessage(message, snapshotMessage));
  });

  return sortTimelineMessages([...mergedSnapshot, ...localPendingMessages]);
};
