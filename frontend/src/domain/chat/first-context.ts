import type { ChatTimelineMessage } from "@/domain/chat/state";

export const FIRST_CONTEXT_QUESTION_IDS = [
  "preferred_name",
  "easy_topic",
  "current_interest",
  "repeating_content",
  "recent_feeling",
  "personal_time",
  "reluctant_routine",
] as const;

export type FirstContextQuestionId =
  (typeof FIRST_CONTEXT_QUESTION_IDS)[number];

export interface FirstContextQuestionContext {
  questionId: FirstContextQuestionId;
  questionText: string;
}

export const FIRST_CONTEXT_INTEREST_QUESTION_IDS = [
  "easy_topic",
  "current_interest",
  "repeating_content",
] as const satisfies readonly FirstContextQuestionId[];

export const FIRST_CONTEXT_LIFE_QUESTION_IDS = [
  "recent_feeling",
  "personal_time",
  "reluctant_routine",
] as const satisfies readonly FirstContextQuestionId[];

export const MAX_FIRST_CONTEXT_ANSWERS = 3;
const CONTINUATION_STORAGE_PREFIX = "magi.first-context-continuation";

export type FirstContextContinuationSelection =
  | {
      mode: "active";
      questionId: FirstContextQuestionId;
      seenQuestionIds: FirstContextQuestionId[];
    }
  | { mode: "dismissed" };

export function isFirstContextQuestionId(
  value: unknown,
): value is FirstContextQuestionId {
  return FIRST_CONTEXT_QUESTION_IDS.includes(value as FirstContextQuestionId);
}

export function readFirstContextQuestionId(
  message: ChatTimelineMessage,
): FirstContextQuestionId | null {
  if (message.role !== "user" || message.payload?.interaction_kind !== "first_context_story") {
    return null;
  }
  const firstContext = message.payload.first_context;
  if (!firstContext || typeof firstContext !== "object") {
    return null;
  }
  const questionId = (firstContext as Record<string, unknown>).question_id;
  return isFirstContextQuestionId(questionId) ? questionId : null;
}

export function answeredFirstContextQuestionIds(
  messages: ChatTimelineMessage[],
): FirstContextQuestionId[] {
  const answered = new Set<FirstContextQuestionId>();
  for (const message of messages) {
    const questionId = readFirstContextQuestionId(message);
    if (questionId) {
      answered.add(questionId);
    }
  }
  return [...answered];
}

function stableIndex(seed: string, size: number): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % Math.max(1, size);
}

function chooseFromPool(
  pool: readonly FirstContextQuestionId[],
  answered: Set<FirstContextQuestionId>,
  seed: string,
): FirstContextQuestionId | null {
  const available = pool.filter((questionId) => !answered.has(questionId));
  if (available.length === 0) {
    return null;
  }
  return available[stableIndex(seed, available.length)] ?? available[0] ?? null;
}

export function chooseNextFirstContextQuestion(
  sessionId: string,
  answeredQuestionIds: readonly FirstContextQuestionId[],
): FirstContextQuestionId | null {
  const answered = new Set(answeredQuestionIds);
  if (!answered.has("preferred_name")) {
    return "preferred_name";
  }
  const interest = chooseFromPool(
    FIRST_CONTEXT_INTEREST_QUESTION_IDS,
    answered,
    `${sessionId}:interest:${answeredQuestionIds.length}`,
  );
  if (
    interest
    && !answeredQuestionIds.some((questionId) =>
      FIRST_CONTEXT_INTEREST_QUESTION_IDS.includes(
        questionId as (typeof FIRST_CONTEXT_INTEREST_QUESTION_IDS)[number],
      ))
  ) {
    return interest;
  }
  const life = chooseFromPool(
    FIRST_CONTEXT_LIFE_QUESTION_IDS,
    answered,
    `${sessionId}:life:${answeredQuestionIds.length}`,
  );
  if (life) {
    return life;
  }
  return interest;
}

export function chooseAlternativeFirstContextQuestion(
  currentQuestionId: FirstContextQuestionId,
  sessionId: string,
  answeredQuestionIds: readonly FirstContextQuestionId[],
  seenQuestionIds: readonly FirstContextQuestionId[] = [],
): FirstContextQuestionId {
  const answered = new Set(answeredQuestionIds);
  const seen = new Set(seenQuestionIds);
  const pool = FIRST_CONTEXT_INTEREST_QUESTION_IDS.includes(
    currentQuestionId as (typeof FIRST_CONTEXT_INTEREST_QUESTION_IDS)[number],
  )
    ? FIRST_CONTEXT_INTEREST_QUESTION_IDS
    : FIRST_CONTEXT_LIFE_QUESTION_IDS.includes(
        currentQuestionId as (typeof FIRST_CONTEXT_LIFE_QUESTION_IDS)[number],
      )
      ? FIRST_CONTEXT_LIFE_QUESTION_IDS
      : FIRST_CONTEXT_QUESTION_IDS.filter(
          (questionId) => questionId !== "preferred_name",
        );
  const eligible = pool.filter(
    (questionId) => questionId !== currentQuestionId && !answered.has(questionId),
  );
  const unseen = eligible.filter((questionId) => !seen.has(questionId));
  const alternatives = unseen.length > 0 ? unseen : eligible;
  if (alternatives.length === 0) {
    return currentQuestionId;
  }
  return (
    alternatives[
      stableIndex(
        `${sessionId}:alternative:${currentQuestionId}:${seenQuestionIds.length}`,
        alternatives.length,
      )
    ] ?? alternatives[0]
  );
}

export function canOfferFirstContextContinuation(
  messages: ChatTimelineMessage[],
  waitingForReply: boolean,
): boolean {
  if (waitingForReply) {
    return false;
  }
  const answered = answeredFirstContextQuestionIds(messages);
  if (answered.length === 0 || answered.length >= MAX_FIRST_CONTEXT_ANSWERS) {
    return false;
  }
  let latestAnswerIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (readFirstContextQuestionId(messages[index])) {
      latestAnswerIndex = index;
      break;
    }
  }
  if (latestAnswerIndex < 0) {
    return false;
  }
  const messagesAfterAnswer = messages.slice(latestAnswerIndex + 1);
  if (messagesAfterAnswer.some((message) => message.role === "user")) {
    return false;
  }
  const lastMessage = messages[messages.length - 1];
  return Boolean(
    messagesAfterAnswer.some((message) => message.role === "assistant")
      && lastMessage
      && lastMessage.role === "assistant"
      && !lastMessage.streaming
      && lastMessage.messageKind !== "assistant_interim",
  );
}

function continuationStorageKey(sessionId: string): string {
  return `${CONTINUATION_STORAGE_PREFIX}:${sessionId}`;
}

export function clearFirstContextContinuationSelections(): boolean {
  if (typeof window === "undefined") {
    return true;
  }
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith(`${CONTINUATION_STORAGE_PREFIX}:`)) {
        keys.push(key);
      }
    }
    for (const key of keys) {
      window.localStorage.removeItem(key);
    }
    for (let index = 0; index < window.localStorage.length; index += 1) {
      if (window.localStorage.key(index)?.startsWith(`${CONTINUATION_STORAGE_PREFIX}:`)) {
        return false;
      }
    }
    return true;
  } catch {
    return false;
  }
}

export function loadFirstContextContinuationSelection(
  sessionId: string | null,
): FirstContextContinuationSelection | null {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId || typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(
      continuationStorageKey(normalizedSessionId),
    );
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed.version !== 1) {
      return null;
    }
    if (parsed.mode === "dismissed") {
      return { mode: "dismissed" };
    }
    if (parsed.mode === "active" && isFirstContextQuestionId(parsed.questionId)) {
      const seenQuestionIds = Array.isArray(parsed.seenQuestionIds)
        ? parsed.seenQuestionIds.filter(isFirstContextQuestionId)
        : [];
      return {
        mode: "active",
        questionId: parsed.questionId,
        seenQuestionIds: seenQuestionIds.includes(parsed.questionId)
          ? seenQuestionIds
          : [...seenQuestionIds, parsed.questionId],
      };
    }
  } catch {
    return null;
  }
  return null;
}

export function saveFirstContextContinuationSelection(
  sessionId: string | null,
  selection: FirstContextContinuationSelection | null,
): void {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId || typeof window === "undefined") {
    return;
  }
  try {
    const key = continuationStorageKey(normalizedSessionId);
    if (!selection) {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(
      key,
      JSON.stringify({ version: 1, ...selection }),
    );
  } catch {
    // Storage failures should not block chat.
  }
}
