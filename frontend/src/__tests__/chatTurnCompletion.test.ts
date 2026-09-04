import { describe, expect, it } from 'vitest';

import type { ChatTimelineMessage } from '@/domain/chat/state';
import { normalizeTerminalRunState } from '@/domain/chat/run-state';
import {
  findLatestPendingResponseTurn,
  getNextRhythmPresentationAt,
  isPendingRunState,
  isTerminalRunState,
  isTurnDurablyTerminal,
  messagesReadyForPresentation,
  resolvePendingTurnFromHistory,
} from '@/domain/chat/turn-completion';

const message = (
  overrides: Partial<ChatTimelineMessage>,
): ChatTimelineMessage => ({
  id: 'message-1',
  role: 'user',
  kind: 'user',
  content: 'hello',
  timestamp: 1,
  turnId: 'turn-1',
  ...overrides,
});

describe('chat turn completion', () => {
  it.each(['blocked', 'cancelled', 'completed', 'failed', 'interrupted', 'merged'])(
    'recognizes %s as terminal',
    (state) => {
      expect(isTerminalRunState(state)).toBe(true);
    },
  );

  it.each(['queued', 'running', 'cancelling'])(
    'recognizes %s as pending',
    (state) => {
      expect(isPendingRunState(state)).toBe(true);
    },
  );

  it('returns the canonical terminal state after transport normalization', () => {
    expect(normalizeTerminalRunState('  BLOCKED ')).toBe('blocked');
    expect(normalizeTerminalRunState('running')).toBeNull();
  });

  it('recognizes a no-visible-response turn from its durable run state', () => {
    expect(isTurnDurablyTerminal([
      message({
        runState: { state: 'completed' } as ChatTimelineMessage['runState'],
      }),
    ], 'turn-1')).toBe(true);
  });

  it('does not infer completion from a final message without durable run state', () => {
    expect(isTurnDurablyTerminal([
      message({
        id: 'assistant-final',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_final',
        streaming: false,
      }),
    ], 'turn-1')).toBe(false);
  });

  it('does not let an old final message override a durable running state', () => {
    expect(isTurnDurablyTerminal([
      message({
        id: 'assistant-final',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_final',
        streaming: false,
        runState: { state: 'running' } as ChatTimelineMessage['runState'],
      }),
    ], 'turn-1')).toBe(false);
  });

  it('does not infer completion from rhythm segments without durable run state', () => {
    const first = message({
      id: 'segment-1',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'assistant_rhythm_segment',
      payload: {
        rhythm: {
          segment_index: 0,
          segment_count: 2,
        },
      },
    });
    const second = message({
      id: 'segment-2',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'assistant_rhythm_segment',
      payload: {
        rhythm: {
          segment_index: 1,
          segment_count: 2,
        },
      },
    });

    expect(isTurnDurablyTerminal([first], 'turn-1')).toBe(false);
    expect(isTurnDurablyTerminal([second, first], 'turn-1')).toBe(false);
  });

  it('ignores terminal evidence from another turn', () => {
    expect(isTurnDurablyTerminal([
      message({
        turnId: 'turn-2',
        runState: { state: 'completed' } as ChatTimelineMessage['runState'],
      }),
    ], 'turn-1')).toBe(false);
  });

  it('restores the newest exact lock from durable non-terminal history', () => {
    const messages = [
      message({
        id: 'old-running',
        turnId: 'turn-old',
        timestamp: 1_000,
        runState: { state: 'running' } as ChatTimelineMessage['runState'],
      }),
      message({
        id: 'new-queued',
        turnId: 'turn-new',
        timestamp: 2_000,
        runState: { state: 'queued' } as ChatTimelineMessage['runState'],
      }),
    ];

    expect(findLatestPendingResponseTurn(messages, 3_000)).toBe('turn-new');
  });

  it('treats a missing turn as settled only for an authoritative history check', () => {
    expect(resolvePendingTurnFromHistory([], 'turn-deleted')).toEqual({
      resolved: true,
      safeToCommitHistory: true,
    });
    expect(resolvePendingTurnFromHistory(
      [],
      'turn-local-race',
      1_000,
      { resolveMissing: false },
    )).toEqual({
      resolved: false,
    });
  });

  it('waits for a complete rhythm turn to reach its planned presentation time', () => {
    const messages = [
      message({
        id: 'segment-1',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_rhythm_segment',
        timestamp: 2_000,
        payload: {
          rhythm: { segment_index: 0, segment_count: 2 },
        },
        runState: { state: 'completed' } as ChatTimelineMessage['runState'],
      }),
      message({
        id: 'segment-2',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_rhythm_segment',
        timestamp: 4_000,
        payload: {
          rhythm: { segment_index: 1, segment_count: 2 },
        },
        runState: { state: 'completed' } as ChatTimelineMessage['runState'],
      }),
    ];

    expect(resolvePendingTurnFromHistory(messages, 'turn-1', 1_000)).toEqual({
      resolved: false,
      safeToCommitHistory: true,
      retryAfterMs: 3_000,
      terminalRunState: 'completed',
    });
    expect(findLatestPendingResponseTurn(messages, 1_000)).toBe('turn-1');
    expect(resolvePendingTurnFromHistory(messages, 'turn-1', 4_000)).toEqual({
      resolved: true,
      safeToCommitHistory: true,
      terminalRunState: 'completed',
    });
    expect(findLatestPendingResponseTurn(messages, 4_000)).toBeNull();
  });

  it('keeps an incomplete terminal rhythm turn locked for a later history check', () => {
    const incomplete = [
      message({
        id: 'segment-1',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_rhythm_segment',
        timestamp: 2_000,
        payload: {
          rhythm: { segment_index: 0, segment_count: 2 },
        },
        runState: { state: 'completed' } as ChatTimelineMessage['runState'],
      }),
    ];

    expect(resolvePendingTurnFromHistory(incomplete, 'turn-1', 5_000)).toEqual({
      resolved: false,
      terminalRunState: 'completed',
    });
    expect(findLatestPendingResponseTurn(incomplete, 5_000)).toBe('turn-1');
  });

  it('only exposes rhythm segments whose planned presentation time has arrived', () => {
    const ordinary = message({
      id: 'ordinary',
      timestamp: 5_000,
    });
    const first = message({
      id: 'segment-1',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'assistant_rhythm_segment',
      timestamp: 2_000,
    });
    const second = message({
      id: 'segment-2',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'assistant_rhythm_segment',
      timestamp: 4_000,
    });
    const messages = [ordinary, first, second];

    expect(messagesReadyForPresentation(messages, 3_000)).toEqual([
      ordinary,
      first,
    ]);
    expect(getNextRhythmPresentationAt(messages, 3_000)).toBe(4_000);
    expect(getNextRhythmPresentationAt(messages, 4_000)).toBeNull();
  });
});
