import { z } from 'zod';
import type { ChatAttachment, UserMessageRequest } from '@/api';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import type { ChatSendConfirmation } from './chatSendReliability';

export const CHAT_RETRYABLE_SEND_STORAGE_KEY = 'magi.chat.retryable-sends';
export const INLINE_SKILL_RETRY_STORAGE_KEY = 'magi.chat.inline-skill-retries';
export const CHAT_RETRYABLE_SEND_STORAGE_VERSION = 1;
export const CHAT_RETRYABLE_SEND_TTL_MS = 24 * 60 * 60 * 1_000;
export const MAX_RETRYABLE_SENDS = 16;

const MAX_FUTURE_CLOCK_SKEW_MS = 5 * 60 * 1_000;

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type RetryableSendDraftKind =
  | 'normal'
  | 'first_context'
  | 'recall_feedback'
  | 'pending_ask';

export type RetryablePendingTurn = {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
  attachments?: ChatAttachment[];
  replyTo?: ChatTimelineReplyPreview | null;
  payload?: Record<string, unknown> | null;
};

export type RetryableAskSendContext = {
  requestId: string;
  sessionId: string;
  messageId: string | null;
  question: string;
  options: string[];
  allowFreeText: boolean;
  expiresAtMs: number | null;
};

export type RetryableAskAnswer = RetryableAskSendContext & {
  answer: string;
  timestamp: number;
};

export type RetryableChatSendOperation = {
  sessionId: string;
  turnId: string;
  createdAtMs: number;
  draftIdentity: string;
  draftSignature: string;
  draftKind: RetryableSendDraftKind;
  request: UserMessageRequest;
  confirmation: ChatSendConfirmation;
  pendingTurn?: RetryablePendingTurn;
  askAnswer?: RetryableAskAnswer;
};

export type RetryableInlineSkillOperation = {
  retryKey: string;
  createdAtMs: number;
  request: UserMessageRequest;
  confirmation: Extract<ChatSendConfirmation, { kind: 'turn' }>;
};

export const deleteRetryableChatSendForTurn = (
  operations: Map<string, RetryableChatSendOperation>,
  sessionId: string,
  turnId: string,
): RetryableChatSendOperation | null => {
  const normalizedSessionId = String(sessionId || '').trim();
  const normalizedTurnId = String(turnId || '').trim();
  const operation = normalizedSessionId
    ? operations.get(normalizedSessionId)
    : undefined;
  if (!operation || operation.turnId !== normalizedTurnId) {
    return null;
  }
  operations.delete(normalizedSessionId);
  return operation;
};

export const deleteRetryableChatSendsForSession = (
  operations: Map<string, RetryableChatSendOperation>,
  sessionId: string,
): RetryableChatSendOperation | null => {
  const normalizedSessionId = String(sessionId || '').trim();
  const operation = normalizedSessionId
    ? operations.get(normalizedSessionId)
    : undefined;
  if (!operation) {
    return null;
  }
  operations.delete(normalizedSessionId);
  return operation;
};

export const deleteRetryableInlineSkillOperationsForTurn = (
  operations: Map<string, RetryableInlineSkillOperation>,
  sessionId: string,
  turnId: string,
): RetryableInlineSkillOperation[] => {
  const normalizedSessionId = String(sessionId || '').trim();
  const normalizedTurnId = String(turnId || '').trim();
  if (!normalizedSessionId || !normalizedTurnId) {
    return [];
  }
  const removed: RetryableInlineSkillOperation[] = [];
  for (const [retryKey, operation] of operations) {
    if (
      String(operation.request.session_id || '').trim() !== normalizedSessionId
      || operation.confirmation.turnId !== normalizedTurnId
    ) {
      continue;
    }
    operations.delete(retryKey);
    removed.push(operation);
  }
  return removed;
};

export const deleteRetryableInlineSkillOperationsForSession = (
  operations: Map<string, RetryableInlineSkillOperation>,
  sessionId: string,
): RetryableInlineSkillOperation[] => {
  const normalizedSessionId = String(sessionId || '').trim();
  if (!normalizedSessionId) {
    return [];
  }
  const removed: RetryableInlineSkillOperation[] = [];
  for (const [retryKey, operation] of operations) {
    if (
      String(operation.request.session_id || '').trim() !== normalizedSessionId
    ) {
      continue;
    }
    operations.delete(retryKey);
    removed.push(operation);
  }
  return removed;
};

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

const requiredId = z.string().min(1).refine(
  (value) => Boolean(value.trim()),
  'Expected a non-blank identifier',
);
const finiteNumber = z.number().finite();
const isJsonValue = (value: unknown, depth = 0): value is JsonValue => {
  if (
    value === null
    || typeof value === 'string'
    || typeof value === 'boolean'
  ) {
    return true;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value);
  }
  if (depth >= 20) {
    return false;
  }
  if (Array.isArray(value)) {
    return value.every((item) => isJsonValue(item, depth + 1));
  }
  if (!value || typeof value !== 'object') {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  return Object.values(value).every(
    (item) => isJsonValue(item, depth + 1),
  );
};
const jsonValueSchema = z.custom<JsonValue>(
  (value) => isJsonValue(value),
  'Expected JSON-safe attachment metadata',
);
const attachmentSchema = z.object({
  attachment_id: requiredId,
  kind: requiredId,
  original_name: z.string(),
  mime_type: z.string().optional(),
  size_bytes: finiteNumber.nonnegative().optional(),
  storage_path: z.string().optional(),
  sha256: z.string().optional(),
  parse_status: z.string().optional(),
  derived_text_excerpt: z.string().optional(),
  derived_text_path: z.string().optional(),
  server_id: z.string().optional(),
  uri: z.string().optional(),
}).catchall(jsonValueSchema);
const recallFeedbackSchema = z.object({
  kind: z.enum(['answer_evidence_mismatch', 'item_irrelevant']),
  target_message_id: requiredId,
  finding_ref: z.string().optional(),
}).strict();
const firstContextSchema = z.object({
  question_id: requiredId,
  question_text: requiredId,
}).strict();
const askMetadataSchema = z.object({
  ask_request_id: requiredId,
}).strict();
const requestSchema = z.object({
  message: z.string(),
  user_id: z.string().optional(),
  session_id: requiredId,
  attachments: z.array(attachmentSchema).max(64).optional(),
  reply_to_message_id: z.string().nullable().optional(),
  workspace_path: z.string().nullable().optional(),
  client_turn_id: requiredId,
  recall_feedback: recallFeedbackSchema.optional(),
  interaction_kind: z.literal('first_context_story').optional(),
  first_context: firstContextSchema.optional(),
  metadata: askMetadataSchema.optional(),
}).strict();
const turnConfirmationSchema = z.object({
  kind: z.literal('turn'),
  sessionId: requiredId,
  turnId: requiredId,
}).strict();
const askConfirmationSchema = z.object({
  kind: z.literal('ask_response'),
  sessionId: requiredId,
  requestId: requiredId,
  answer: z.string(),
}).strict();
const confirmationSchema = z.discriminatedUnion('kind', [
  turnConfirmationSchema,
  askConfirmationSchema,
]);
const replyPreviewSchema = z.object({
  messageId: requiredId,
  role: z.enum(['user', 'assistant']),
  messageKind: z.string().nullable().optional(),
  contentExcerpt: z.string(),
}).strict();
const pendingPayloadSchema = z.union([
  z.object({
    recall_feedback: recallFeedbackSchema,
  }).strict(),
  z.object({
    interaction_kind: z.literal('first_context_story'),
    first_context: firstContextSchema,
  }).strict(),
]);
const pendingTurnSchema = z.object({
  sessionId: requiredId,
  input: z.string(),
  turnId: requiredId,
  timestamp: finiteNumber,
  pendingLabel: z.string(),
  attachments: z.array(attachmentSchema).max(64).optional(),
  replyTo: replyPreviewSchema.nullable().optional(),
  payload: pendingPayloadSchema.nullable().optional(),
}).strict();
const askAnswerSchema = z.object({
  requestId: requiredId,
  sessionId: requiredId,
  messageId: z.string().nullable(),
  question: z.string(),
  options: z.array(z.string()).max(64),
  allowFreeText: z.boolean(),
  expiresAtMs: finiteNumber.nullable(),
  answer: z.string(),
  timestamp: finiteNumber,
}).strict();
const operationSchema = z.object({
  sessionId: requiredId,
  turnId: requiredId,
  createdAtMs: finiteNumber,
  draftIdentity: z.string(),
  draftSignature: z.string(),
  draftKind: z.enum(['normal', 'first_context', 'recall_feedback', 'pending_ask']),
  request: requestSchema,
  confirmation: confirmationSchema,
  pendingTurn: pendingTurnSchema.optional(),
  askAnswer: askAnswerSchema.optional(),
}).strict().superRefine((operation, context) => {
  const addIssue = (message: string) => {
    context.addIssue({
      code: 'custom',
      message,
    });
  };
  if (
    operation.request.session_id !== operation.sessionId
    || operation.request.client_turn_id !== operation.turnId
    || operation.confirmation.sessionId !== operation.sessionId
  ) {
    addIssue('Operation identity fields do not match');
  }
  if (
    operation.pendingTurn
    && (
      operation.pendingTurn.sessionId !== operation.sessionId
      || operation.pendingTurn.turnId !== operation.turnId
      || operation.pendingTurn.input !== operation.request.message
    )
  ) {
    addIssue('Pending turn fields do not match the request');
  }
  if (operation.draftKind === 'normal') {
    if (
      operation.confirmation.kind !== 'turn'
      || operation.confirmation.turnId !== operation.turnId
      || !operation.pendingTurn
      || operation.request.recall_feedback
      || operation.request.interaction_kind
      || operation.request.first_context
      || operation.request.metadata
      || operation.askAnswer
    ) {
      addIssue('Normal operation fields are inconsistent');
    }
    return;
  }
  if (operation.draftKind === 'first_context') {
    const pendingPayload = operation.pendingTurn?.payload;
    const hasFirstContextPayload = Boolean(
      pendingPayload
      && 'interaction_kind' in pendingPayload
      && pendingPayload.interaction_kind === 'first_context_story'
      && 'first_context' in pendingPayload
      && pendingPayload.first_context,
    );
    if (
      operation.confirmation.kind !== 'turn'
      || operation.confirmation.turnId !== operation.turnId
      || !operation.pendingTurn
      || operation.request.interaction_kind !== 'first_context_story'
      || !operation.request.first_context
      || !hasFirstContextPayload
      || operation.request.recall_feedback
      || operation.request.metadata
      || operation.askAnswer
    ) {
      addIssue('First-context operation fields are inconsistent');
    }
    return;
  }
  if (operation.draftKind === 'recall_feedback') {
    if (
      operation.confirmation.kind !== 'turn'
      || operation.confirmation.turnId !== operation.turnId
      || !operation.pendingTurn
      || !operation.request.recall_feedback
      || operation.request.metadata
      || operation.askAnswer
    ) {
      addIssue('Recall feedback operation fields are inconsistent');
    }
    return;
  }
  if (
    operation.confirmation.kind !== 'ask_response'
    || operation.pendingTurn
    || !operation.askAnswer
    || operation.request.metadata?.ask_request_id
      !== operation.confirmation.requestId
    || operation.request.message !== operation.confirmation.answer
    || operation.askAnswer?.requestId !== operation.confirmation.requestId
    || operation.askAnswer?.sessionId !== operation.sessionId
    || operation.askAnswer?.answer !== operation.confirmation.answer
  ) {
    addIssue('Pending ask operation fields are inconsistent');
  }
});
const inlineSkillOperationSchema = z.object({
  retryKey: z.string().min(1).max(200_000),
  createdAtMs: finiteNumber,
  request: requestSchema,
  confirmation: turnConfirmationSchema,
}).strict().superRefine((operation, context) => {
  let retryParts: unknown;
  try {
    retryParts = JSON.parse(operation.retryKey);
  } catch {
    retryParts = null;
  }
  const retryPartArray = Array.isArray(retryParts) ? retryParts : null;
  const validRetryParts = (
    retryPartArray
    && retryPartArray.length === 4
    && typeof retryPartArray[0] === 'string'
    && Boolean(retryPartArray[0].trim())
    && (
      retryPartArray[1] === null
      || typeof retryPartArray[1] === 'string'
    )
    && typeof retryPartArray[2] === 'string'
    && Boolean(retryPartArray[2].trim())
    && Array.isArray(retryPartArray[3])
    && retryPartArray[3].length <= 128
    && retryPartArray[3].every(
      (argument) => typeof argument === 'string',
    )
  );
  if (
    !validRetryParts
    || retryPartArray?.[0] !== operation.request.session_id
    || retryPartArray?.[1] !== (operation.request.workspace_path ?? null)
    || operation.request.session_id !== operation.confirmation.sessionId
    || operation.request.client_turn_id !== operation.confirmation.turnId
    || operation.request.attachments
    || operation.request.reply_to_message_id
    || operation.request.recall_feedback
    || operation.request.interaction_kind
    || operation.request.first_context
    || operation.request.metadata
  ) {
    context.addIssue({
      code: 'custom',
      message: 'Inline skill operation fields are inconsistent',
    });
  }
});
const envelopeSchema = z.object({
  version: z.literal(CHAT_RETRYABLE_SEND_STORAGE_VERSION),
  operations: z.array(z.unknown()).max(MAX_RETRYABLE_SENDS * 4),
}).strict();
const inlineSkillEnvelopeSchema = z.object({
  version: z.literal(CHAT_RETRYABLE_SEND_STORAGE_VERSION),
  operations: z.array(z.unknown()).max(MAX_RETRYABLE_SENDS * 4),
}).strict();

const getSessionStorage = (): StorageLike | null => {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
};

const removeStoredOperations = (
  storage: StorageLike,
  key = CHAT_RETRYABLE_SEND_STORAGE_KEY,
): void => {
  try {
    storage.removeItem(key);
  } catch {
    // Storage failures must never block chat.
  }
};

const isFreshTimestamp = (
  createdAtMs: number,
  nowMs: number,
): boolean => (
  createdAtMs <= nowMs + MAX_FUTURE_CLOCK_SKEW_MS
  && nowMs - createdAtMs <= CHAT_RETRYABLE_SEND_TTL_MS
);

export const isRetryableChatSendFresh = (
  operation: RetryableChatSendOperation,
  nowMs: number,
): boolean => isFreshTimestamp(operation.createdAtMs, nowMs);

export const isRetryableInlineSkillFresh = (
  operation: RetryableInlineSkillOperation,
  nowMs: number,
): boolean => isFreshTimestamp(operation.createdAtMs, nowMs);

export const saveRetryableChatSends = (
  operations: Map<string, RetryableChatSendOperation>,
  storage: StorageLike | null = getSessionStorage(),
  nowMs = Date.now(),
): void => {
  if (!storage) {
    return;
  }
  const snapshots = [...operations.values()]
    .filter((operation) => isRetryableChatSendFresh(operation, nowMs))
    .map((operation) => operationSchema.safeParse(operation))
    .filter((result) => result.success)
    .map((result) => result.data as RetryableChatSendOperation)
    .sort((left, right) => left.createdAtMs - right.createdAtMs)
    .slice(-MAX_RETRYABLE_SENDS);
  try {
    if (snapshots.length === 0) {
      storage.removeItem(CHAT_RETRYABLE_SEND_STORAGE_KEY);
      return;
    }
    storage.setItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: snapshots,
      }),
    );
  } catch {
    // Storage failures must never block chat.
  }
};

export const loadRetryableChatSends = (
  nowMs = Date.now(),
  storage: StorageLike | null = getSessionStorage(),
): Map<string, RetryableChatSendOperation> => {
  const operations = new Map<string, RetryableChatSendOperation>();
  if (!storage) {
    return operations;
  }
  let raw: string | null;
  try {
    raw = storage.getItem(CHAT_RETRYABLE_SEND_STORAGE_KEY);
  } catch {
    return operations;
  }
  if (!raw) {
    return operations;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    removeStoredOperations(storage);
    return operations;
  }
  const envelope = envelopeSchema.safeParse(parsed);
  if (!envelope.success) {
    removeStoredOperations(storage);
    return operations;
  }

  const freshOperations = envelope.data.operations
    .map((operation) => operationSchema.safeParse(operation))
    .filter((result) => result.success)
    .map((result) => result.data as RetryableChatSendOperation)
    .filter((operation) => isRetryableChatSendFresh(operation, nowMs))
    .sort((left, right) => left.createdAtMs - right.createdAtMs);
  for (const operation of freshOperations) {
    operations.set(
      operation.sessionId,
      operation as RetryableChatSendOperation,
    );
  }
  while (operations.size > MAX_RETRYABLE_SENDS) {
    const oldestSessionId = operations.keys().next().value;
    if (typeof oldestSessionId !== 'string') {
      break;
    }
    operations.delete(oldestSessionId);
  }
  saveRetryableChatSends(operations, storage, nowMs);
  return operations;
};

export const saveRetryableInlineSkillOperations = (
  operations: Map<string, RetryableInlineSkillOperation>,
  storage: StorageLike | null = getSessionStorage(),
  nowMs = Date.now(),
): void => {
  if (!storage) {
    return;
  }
  const snapshots = [...operations.values()]
    .filter((operation) => isFreshTimestamp(operation.createdAtMs, nowMs))
    .map((operation) => inlineSkillOperationSchema.safeParse(operation))
    .filter((result) => result.success)
    .map((result) => result.data as RetryableInlineSkillOperation)
    .sort((left, right) => left.createdAtMs - right.createdAtMs)
    .slice(-MAX_RETRYABLE_SENDS);
  try {
    if (snapshots.length === 0) {
      storage.removeItem(INLINE_SKILL_RETRY_STORAGE_KEY);
      return;
    }
    storage.setItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: snapshots,
      }),
    );
  } catch {
    // Storage failures must never block chat.
  }
};

export const loadRetryableInlineSkillOperations = (
  nowMs = Date.now(),
  storage: StorageLike | null = getSessionStorage(),
): Map<string, RetryableInlineSkillOperation> => {
  const operations = new Map<string, RetryableInlineSkillOperation>();
  if (!storage) {
    return operations;
  }
  let raw: string | null;
  try {
    raw = storage.getItem(INLINE_SKILL_RETRY_STORAGE_KEY);
  } catch {
    return operations;
  }
  if (!raw) {
    return operations;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    removeStoredOperations(storage, INLINE_SKILL_RETRY_STORAGE_KEY);
    return operations;
  }
  const envelope = inlineSkillEnvelopeSchema.safeParse(parsed);
  if (!envelope.success) {
    removeStoredOperations(storage, INLINE_SKILL_RETRY_STORAGE_KEY);
    return operations;
  }
  const freshOperations = envelope.data.operations
    .map((operation) => inlineSkillOperationSchema.safeParse(operation))
    .filter((result) => result.success)
    .map((result) => result.data as RetryableInlineSkillOperation)
    .filter((operation) => isFreshTimestamp(operation.createdAtMs, nowMs))
    .sort((left, right) => left.createdAtMs - right.createdAtMs);
  for (const operation of freshOperations) {
    operations.set(operation.retryKey, operation);
  }
  while (operations.size > MAX_RETRYABLE_SENDS) {
    const oldestRetryKey = operations.keys().next().value;
    if (typeof oldestRetryKey !== 'string') {
      break;
    }
    operations.delete(oldestRetryKey);
  }
  saveRetryableInlineSkillOperations(operations, storage, nowMs);
  return operations;
};
