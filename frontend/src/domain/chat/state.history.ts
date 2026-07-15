import type {
  ChatHistoryMessage,
  ChatMessageLabel,
  ChatReplyPreview,
} from '@/api';
import type {
  ChatMessageKind,
  ChatTimelineMessage,
  ChatTimelineMessageLabel,
  ChatTimelineReplyPreview,
  RecalledMemory,
  RecalledMemorySummary,
} from '@/domain/chat/state';
import { normalizeTraceSummary } from '@/domain/chat/state.trace';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';

export const normalizeRecalledMemories = (raw: unknown): RecalledMemory[] | undefined => {
  if (!Array.isArray(raw)) {
    return undefined;
  }
  const items: RecalledMemory[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const statement = String(record.statement || '').trim();
    if (!statement) {
      continue;
    }
    const confidenceRaw = record.confidence;
    const confidence = typeof confidenceRaw === 'number' && Number.isFinite(confidenceRaw)
      ? confidenceRaw
      : null;
    const occurredAtRaw = record.occurred_at;
    const occurredAt = typeof occurredAtRaw === 'number' && Number.isFinite(occurredAtRaw)
      ? occurredAtRaw
      : null;
    const evidenceText = typeof record.evidence_text === 'string'
      ? record.evidence_text.trim() || null
      : null;
    const feedbackRef = typeof record.feedback_ref === 'string'
      ? record.feedback_ref.trim() || null
      : null;
    items.push({
      kind: String(record.kind || 'event'),
      sourceLayer: String(record.source_layer || 'L1'),
      statement,
      topic: String(record.topic || statement),
      confidence,
      occurredAt,
      evidenceText,
      feedbackRef,
    });
  }
  return items.length > 0 ? items : undefined;
};

export const normalizeRecalledMemorySummary = (raw: unknown): RecalledMemorySummary | undefined => {
  if (!raw || typeof raw !== 'object') {
    return undefined;
  }
  const record = raw as Record<string, unknown>;
  const canClaimTotal = record.can_claim_total === true;
  const coverageKind = String(record.coverage_kind || '').trim();
  if (!canClaimTotal && !coverageKind) {
    return undefined;
  }
  const totalCountRaw = record.total_count;
  const totalCount = typeof totalCountRaw === 'number' && Number.isFinite(totalCountRaw)
    ? totalCountRaw
    : null;
  const domain = typeof record.domain === 'string' ? record.domain.trim() || null : null;
  return {
    coverageKind: coverageKind || 'unknown',
    canClaimTotal,
    totalCount,
    domain,
  };
};

const normalizeReplyPreview = (
  preview: ChatReplyPreview | null | undefined,
): ChatTimelineReplyPreview | null => {
  if (!preview || typeof preview !== 'object') {
    return null;
  }
  const messageId = String(preview.message_id || '').trim();
  if (!messageId) {
    return null;
  }
  return {
    messageId,
    role: preview.role === 'user' ? 'user' : 'assistant',
    messageKind: preview.message_kind || null,
    contentExcerpt: String(preview.content_excerpt || '').trim(),
  };
};

export const normalizeMessageLabel = (
  label: ChatMessageLabel | null | undefined,
): ChatTimelineMessageLabel | null => {
  if (!label || typeof label !== 'object') {
    return null;
  }
  const kind = String(label.kind || '').trim();
  const text = String(label.text || '').trim();
  const appliedBy = String(label.applied_by || '').trim();
  const source = String(label.source || '').trim();
  const createdAtMs = Number(label.created_at_ms || 0);
  if (!kind || !text || !appliedBy || !source || createdAtMs <= 0) {
    return null;
  }
  return {
    kind,
    text,
    appliedBy,
    source,
    createdAtMs,
  };
};

export const normalizeHistoryMessages = (messages: ChatHistoryMessage[]): ChatTimelineMessage[] => {
  const normalizedMessages: ChatTimelineMessage[] = [];

  messages.forEach((message, index) => {
    const rawMessageKind = String(message.message_kind || '').trim();
    const kind = (message.kind || message.role) as ChatMessageKind;
    const traceSummary = normalizeTraceSummary(message.trace_summary);
    const normalizedMessage: ChatTimelineMessage = {
      id: String(message.message_id || `${message.turn_id || 'history'}-${index}-${kind}`),
      role: message.role === 'user' ? 'user' : 'assistant',
      kind,
      content: message.content,
      timestamp: normalizeChatTimestamp(message.timestamp),
      messageId: message.message_id || undefined,
      messageKind: message.message_kind || null,
      personaId: message.persona_id || null,
      turnId: message.turn_id || undefined,
      traceDisplayMode: message.trace_display_mode || null,
      allowTraceCollapse: Boolean(message.allow_trace_collapse),
      attachments: Array.isArray(message.attachments) ? message.attachments : undefined,
      replyTo: normalizeReplyPreview(message.reply_to),
      label: normalizeMessageLabel(message.label),
      traceSummary,
      traceAvailable: Boolean(message.trace_available || traceSummary?.traceAvailable),
      runState: message.run_state || null,
      recalledMemories: normalizeRecalledMemories(
        message.payload && typeof message.payload === 'object'
          ? (message.payload as Record<string, unknown>).recalled_memories
          : null,
      ),
      recalledMemorySummary: normalizeRecalledMemorySummary(
        message.payload && typeof message.payload === 'object'
          ? (message.payload as Record<string, unknown>).recalled_memory_summary
          : null,
      ),
      payload:
        message.payload && typeof message.payload === 'object'
          ? (message.payload as Record<string, unknown>)
          : null,
    };

    if (rawMessageKind === 'assistant_reaction') {
      const turnId = String(normalizedMessage.turnId || '').trim();
      const targetIndex = [...normalizedMessages]
        .map((item, itemIndex) => ({ item, itemIndex }))
        .reverse()
        .find(({ item }) => item.role === 'user' && String(item.turnId || '').trim() === turnId)
        ?.itemIndex;
      if (targetIndex !== undefined) {
        normalizedMessages[targetIndex] = {
          ...normalizedMessages[targetIndex],
          reaction: normalizedMessage.content,
        };
        return;
      }
    }

    normalizedMessages.push(normalizedMessage);
  });

  return normalizedMessages;
};
