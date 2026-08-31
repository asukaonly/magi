import type { ChatTimelineMessage } from './state';
import {
  orderCompleteRhythmItems,
  readRhythmSegmentMeta,
} from './rhythm';

const TERMINAL_RUN_STATES = new Set([
  'blocked',
  'cancelled',
  'completed',
  'failed',
  'interrupted',
  'merged',
]);

const PENDING_RUN_STATES = new Set([
  'queued',
  'running',
  'cancelling',
]);

export type PendingResponseTurnIdentity = {
  sessionId: string;
  turnId: string;
};

export type PendingResponseTurnsBySession = Readonly<Record<string, string>>;

export type PendingTurnHistoryResolution = {
  resolved: boolean;
  safeToCommitHistory?: boolean;
  retryAfterMs?: number;
  terminalRunState?: string;
};

type ResolvePendingTurnOptions = {
  resolveMissing?: boolean;
};

type RhythmPresentationState = {
  kind: 'none' | 'incomplete' | 'complete';
  presentationAtMs: number | null;
};

export const isTerminalRunState = (state: unknown): boolean => (
  TERMINAL_RUN_STATES.has(String(state || '').trim().toLowerCase())
);

export const isPendingRunState = (state: unknown): boolean => (
  PENDING_RUN_STATES.has(String(state || '').trim().toLowerCase())
);

const getTurnMessages = (
  messages: ChatTimelineMessage[],
  turnId: string,
): ChatTimelineMessage[] => {
  const normalizedTurnId = String(turnId || '').trim();
  if (!normalizedTurnId) {
    return [];
  }
  return messages.filter(
    (message) => String(message.turnId || '').trim() === normalizedTurnId,
  );
};

const getRhythmPresentationState = (
  messages: ChatTimelineMessage[],
): RhythmPresentationState => {
  const rhythmMessages = messages.filter(
    (message) => String(message.messageKind || '').trim() === 'assistant_rhythm_segment',
  );
  if (rhythmMessages.length === 0) {
    return { kind: 'none', presentationAtMs: null };
  }
  const ordered = orderCompleteRhythmItems(
    rhythmMessages,
    (message) => readRhythmSegmentMeta(message.payload?.rhythm),
  );
  if (!ordered) {
    return { kind: 'incomplete', presentationAtMs: null };
  }
  return {
    kind: 'complete',
    presentationAtMs: ordered.reduce(
      (latest, message) => Math.max(latest, Number(message.timestamp) || 0),
      0,
    ),
  };
};

export const isTurnDurablyTerminal = (
  messages: ChatTimelineMessage[],
  turnId: string,
): boolean => {
  const turnMessages = getTurnMessages(messages, turnId);
  const durableRunStates = turnMessages
    .map((message) => message.runState?.state)
    .filter((state) => String(state || '').trim());
  if (durableRunStates.some(isPendingRunState)) {
    return false;
  }
  return durableRunStates.some(isTerminalRunState);
};

export const resolvePendingTurnFromHistory = (
  messages: ChatTimelineMessage[],
  turnId: string,
  nowMs: number = Date.now(),
  options: ResolvePendingTurnOptions = {},
): PendingTurnHistoryResolution => {
  const turnMessages = getTurnMessages(messages, turnId);
  if (turnMessages.length === 0) {
    const resolved = options.resolveMissing !== false;
    return resolved
      ? { resolved: true, safeToCommitHistory: true }
      : { resolved: false };
  }
  if (!isTurnDurablyTerminal(turnMessages, turnId)) {
    return { resolved: false };
  }
  const terminalRunState = turnMessages
    .map((message) => String(message.runState?.state || '').trim().toLowerCase())
    .find(isTerminalRunState);
  const rhythmPresentation = getRhythmPresentationState(turnMessages);
  if (rhythmPresentation.kind === 'incomplete') {
    return {
      resolved: false,
      terminalRunState,
    };
  }
  const presentationAtMs = rhythmPresentation.presentationAtMs;
  if (presentationAtMs !== null && presentationAtMs > nowMs) {
    return {
      resolved: false,
      safeToCommitHistory: true,
      retryAfterMs: Math.max(1, presentationAtMs - nowMs),
      terminalRunState,
    };
  }
  return {
    resolved: true,
    safeToCommitHistory: true,
    terminalRunState,
  };
};

export const findLatestPendingResponseTurn = (
  messages: ChatTimelineMessage[],
  nowMs: number = Date.now(),
): string | null => {
  const turns = new Map<string, ChatTimelineMessage[]>();
  for (const message of messages) {
    const turnId = String(message.turnId || '').trim();
    if (!turnId) {
      continue;
    }
    const current = turns.get(turnId);
    if (current) {
      current.push(message);
    } else {
      turns.set(turnId, [message]);
    }
  }

  let latest: { turnId: string; timestamp: number } | null = null;
  for (const [turnId, turnMessages] of turns) {
    const states = turnMessages.map((message) => message.runState?.state);
    const hasPendingRun = states.some(isPendingRunState);
    const rhythmPresentation = getRhythmPresentationState(turnMessages);
    const presentationAtMs = rhythmPresentation.presentationAtMs;
    const isPresentingDurableRhythm = (
      states.some(isTerminalRunState)
      && (
        rhythmPresentation.kind === 'incomplete'
        || (presentationAtMs !== null && presentationAtMs > nowMs)
      )
    );
    if (!hasPendingRun && !isPresentingDurableRhythm) {
      continue;
    }
    const timestamp = turnMessages.reduce(
      (value, message) => Math.max(value, Number(message.timestamp) || 0),
      0,
    );
    if (!latest || timestamp >= latest.timestamp) {
      latest = { turnId, timestamp };
    }
  }
  return latest?.turnId || null;
};

export const getNextRhythmPresentationAt = (
  messages: ChatTimelineMessage[],
  nowMs: number,
): number | null => {
  let nextPresentationAt: number | null = null;
  for (const message of messages) {
    if (String(message.messageKind || '').trim() !== 'assistant_rhythm_segment') {
      continue;
    }
    const timestamp = Number(message.timestamp) || 0;
    if (timestamp <= nowMs) {
      continue;
    }
    if (nextPresentationAt === null || timestamp < nextPresentationAt) {
      nextPresentationAt = timestamp;
    }
  }
  return nextPresentationAt;
};

export const messagesReadyForPresentation = (
  messages: ChatTimelineMessage[],
  nowMs: number,
): ChatTimelineMessage[] => messages.filter((message) => (
  String(message.messageKind || '').trim() !== 'assistant_rhythm_segment'
  || (Number(message.timestamp) || 0) <= nowMs
));
