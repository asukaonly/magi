import type { ChatTimelineReplyPreview } from '@/domain/chat/state';

export type RecallFeedbackKind = 'answer_evidence_mismatch' | 'item_irrelevant';

export type RecallFeedbackRequest = {
  kind: RecallFeedbackKind;
  target_message_id: string;
  finding_ref?: string;
};

export type RecallFeedbackDraft = {
  kind: RecallFeedbackKind;
  targetMessageId: string;
  targetMessageExcerpt: string;
  findingRef?: string;
  findingLabel?: string;
  customText: string | null;
};

export type RecallFeedbackDraftInput = Omit<RecallFeedbackDraft, 'customText'>;

type Translate = (key: string, options?: Record<string, unknown>) => string;

export const compactRecallFeedbackFindingLabel = (
  value: string,
  maxLength = 120,
): string => {
  const normalized = value.trim();
  if (maxLength <= 0) {
    return '';
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(maxLength - 1, 0)).trimEnd()}…`;
};

export const buildRecallFeedbackDraftText = (
  draft: RecallFeedbackDraft,
  translate: Translate,
): string => {
  if (draft.customText !== null) {
    return draft.customText;
  }
  if (draft.kind === 'item_irrelevant') {
    return translate('chat.recallFeedback.templates.itemIrrelevant', {
      title: draft.findingLabel || translate('chat.recallFeedback.thisRecord'),
    });
  }
  return translate('chat.recallFeedback.templates.answerEvidenceMismatch');
};

export const toRecallFeedbackRequest = (
  draft: RecallFeedbackDraft,
): RecallFeedbackRequest => ({
  kind: draft.kind,
  target_message_id: draft.targetMessageId,
  ...(draft.findingRef ? { finding_ref: draft.findingRef } : {}),
});

export const toRecallFeedbackReplyPreview = (
  draft: RecallFeedbackDraft,
): ChatTimelineReplyPreview => ({
  messageId: draft.targetMessageId,
  role: 'assistant',
  contentExcerpt: draft.targetMessageExcerpt,
});
