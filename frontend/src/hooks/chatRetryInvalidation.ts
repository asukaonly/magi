import {
  captureBrowserContentGeneration,
  isBrowserContentGenerationCurrent,
  type BrowserContentGeneration,
} from '@/lib/browserContentGeneration';

export type ChatRetryGuard = {
  browserContentGeneration: BrowserContentGeneration;
  globalEpoch: number;
  sessionId: string;
  sessionEpoch: number;
  turnId: string | null;
  turnEpoch: number;
};

let globalEpoch = 0;
const sessionEpochs = new Map<string, number>();
const turnEpochsBySession = new Map<string, Map<string, number>>();
let historyGlobalEpoch = 0;
const historySessionEpochs = new Map<string, number>();

const normalizeId = (value: string | null | undefined): string => (
  String(value || '').trim()
);

const getSessionEpoch = (sessionId: string): number => (
  sessionEpochs.get(sessionId) ?? 0
);

const getTurnEpoch = (sessionId: string, turnId: string | null): number => {
  if (!turnId) {
    return 0;
  }
  return turnEpochsBySession.get(sessionId)?.get(turnId) ?? 0;
};

export const captureChatRetryGuard = (
  sessionId: string,
  turnId?: string | null,
): ChatRetryGuard => {
  const normalizedSessionId = normalizeId(sessionId);
  const normalizedTurnId = normalizeId(turnId) || null;
  return {
    browserContentGeneration: captureBrowserContentGeneration(),
    globalEpoch,
    sessionId: normalizedSessionId,
    sessionEpoch: getSessionEpoch(normalizedSessionId),
    turnId: normalizedTurnId,
    turnEpoch: getTurnEpoch(normalizedSessionId, normalizedTurnId),
  };
};

export const isChatRetryGuardCurrent = (guard: ChatRetryGuard): boolean => (
  isBrowserContentGenerationCurrent(guard.browserContentGeneration)
  && guard.globalEpoch === globalEpoch
  && guard.sessionEpoch === getSessionEpoch(guard.sessionId)
  && guard.turnEpoch === getTurnEpoch(guard.sessionId, guard.turnId)
);

export const areChatRetryGuardsCurrent = (
  ...guards: ChatRetryGuard[]
): boolean => guards.every(isChatRetryGuardCurrent);

export const invalidateChatRetryTurn = (
  sessionId: string,
  turnId: string,
): void => {
  const normalizedSessionId = normalizeId(sessionId);
  const normalizedTurnId = normalizeId(turnId);
  if (!normalizedSessionId || !normalizedTurnId) {
    return;
  }
  const turns = turnEpochsBySession.get(normalizedSessionId) ?? new Map();
  turns.set(normalizedTurnId, (turns.get(normalizedTurnId) ?? 0) + 1);
  turnEpochsBySession.set(normalizedSessionId, turns);
};

export const invalidateChatRetrySession = (sessionId: string): void => {
  const normalizedSessionId = normalizeId(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  sessionEpochs.set(
    normalizedSessionId,
    getSessionEpoch(normalizedSessionId) + 1,
  );
  turnEpochsBySession.delete(normalizedSessionId);
};

export const invalidateAllChatRetries = (): void => {
  globalEpoch += 1;
  sessionEpochs.clear();
  turnEpochsBySession.clear();
};

export type ChatHistoryGuard = {
  browserContentGeneration: BrowserContentGeneration;
  globalEpoch: number;
  sessionId: string;
  sessionEpoch: number;
};

export const captureChatHistoryGuard = (
  sessionId: string,
): ChatHistoryGuard => {
  const normalizedSessionId = normalizeId(sessionId);
  return {
    browserContentGeneration: captureBrowserContentGeneration(),
    globalEpoch: historyGlobalEpoch,
    sessionId: normalizedSessionId,
    sessionEpoch: historySessionEpochs.get(normalizedSessionId) ?? 0,
  };
};

export const isChatHistoryGuardCurrent = (
  guard: ChatHistoryGuard,
): boolean => (
  isBrowserContentGenerationCurrent(guard.browserContentGeneration)
  && guard.globalEpoch === historyGlobalEpoch
  && guard.sessionEpoch === (
    historySessionEpochs.get(guard.sessionId) ?? 0
  )
);

export const invalidateChatHistorySession = (sessionId: string): void => {
  const normalizedSessionId = normalizeId(sessionId);
  if (!normalizedSessionId) {
    return;
  }
  historySessionEpochs.set(
    normalizedSessionId,
    (historySessionEpochs.get(normalizedSessionId) ?? 0) + 1,
  );
};

export const invalidateAllChatHistory = (): void => {
  historyGlobalEpoch += 1;
  historySessionEpochs.clear();
};
