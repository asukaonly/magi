import { beforeEach, describe, expect, it } from 'vitest';
import {
  CHAT_RETRYABLE_SEND_STORAGE_KEY,
  CHAT_RETRYABLE_SEND_STORAGE_VERSION,
  CHAT_RETRYABLE_SEND_TTL_MS,
  deleteRetryableChatSendForTurn,
  deleteRetryableChatSendsForSession,
  deleteRetryableInlineSkillOperationsForSession,
  deleteRetryableInlineSkillOperationsForTurn,
  INLINE_SKILL_RETRY_STORAGE_KEY,
  loadRetryableInlineSkillOperations,
  loadRetryableChatSends,
  MAX_RETRYABLE_SENDS,
  saveRetryableInlineSkillOperations,
  saveRetryableChatSends,
  type RetryableChatSendOperation,
  type RetryableInlineSkillOperation,
} from '@/hooks/chatRetryableSendStorage';

const NOW_MS = 1_800_000_000_000;

const buildOperation = (
  index = 0,
  createdAtMs = NOW_MS + index,
): RetryableChatSendOperation => {
  const sessionId = `session-${index}`;
  const turnId = `turn-${index}`;
  const attachment = {
    attachment_id: `attachment-${index}`,
    kind: 'text_file',
    original_name: `notes-${index}.txt`,
    mime_type: 'text/plain',
    size_bytes: 12,
    storage_path: `/tmp/notes-${index}.txt`,
    sha256: `sha-${index}`,
    parse_status: 'parsed',
    session_id: sessionId,
    turn_id: turnId,
    character_count: 12,
    truncated: false,
    encoding: 'utf-8',
    page_count: 0,
    extraction_succeeded: true,
    parse_error: null,
  };
  return {
    sessionId,
    turnId,
    createdAtMs,
    draftIdentity: `identity-${index}`,
    draftSignature: `signature-${index}`,
    draftKind: 'normal',
    request: {
      user_id: 'local_user',
      session_id: sessionId,
      message: `message-${index}`,
      attachments: [attachment],
      reply_to_message_id: null,
      workspace_path: null,
      client_turn_id: turnId,
    },
    confirmation: {
      kind: 'turn',
      sessionId,
      turnId,
    },
    pendingTurn: {
      sessionId,
      input: `message-${index}`,
      turnId,
      timestamp: createdAtMs,
      pendingLabel: 'Pending',
      attachments: [attachment],
      replyTo: null,
    },
  };
};

const buildInlineSkillOperation = (
  index = 0,
  createdAtMs = NOW_MS + index,
): RetryableInlineSkillOperation => {
  const sessionId = `skill-session-${index}`;
  const turnId = `skill-turn-${index}`;
  return {
    retryKey: JSON.stringify([
      sessionId,
      null,
      'summarize',
      [`arg-${index}`],
    ]),
    createdAtMs,
    request: {
      user_id: 'local_user',
      session_id: sessionId,
      message: `/summarize arg-${index}\n\nOriginal expanded body ${index}`,
      workspace_path: null,
      client_turn_id: turnId,
    },
    confirmation: {
      kind: 'turn',
      sessionId,
      turnId,
    },
  };
};

describe('chat retryable send storage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('round-trips complete JSON attachment metadata', () => {
    const operation = buildOperation();
    operation.request.run_disposition = 'replace';
    saveRetryableChatSends(
      new Map([[operation.sessionId, operation]]),
      window.sessionStorage,
      NOW_MS,
    );

    const loaded = loadRetryableChatSends(NOW_MS, window.sessionStorage);

    expect(loaded.get(operation.sessionId)?.request.attachments).toEqual(
      operation.request.attachments,
    );
    expect(
      loaded.get(operation.sessionId)?.pendingTurn?.attachments,
    ).toEqual(operation.pendingTurn?.attachments);
    expect(loaded.get(operation.sessionId)?.request.run_disposition).toBe('replace');
    expect(JSON.parse(
      window.sessionStorage.getItem(CHAT_RETRYABLE_SEND_STORAGE_KEY) || '{}',
    )).toMatchObject({
      version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
    });
  });

  it('round-trips a first-context answer with its question', () => {
    const operation = buildOperation();
    operation.draftKind = 'first_context';
    operation.request.attachments = [];
    operation.pendingTurn!.attachments = [];
    operation.request.interaction_kind = 'first_context_story';
    operation.request.first_context = {
      question_id: 'current_interest',
      question_text: '最近有什么东西，是你愿意主动花时间了解的？',
    };
    operation.pendingTurn!.payload = {
      interaction_kind: 'first_context_story',
      first_context: operation.request.first_context,
    };

    saveRetryableChatSends(
      new Map([[operation.sessionId, operation]]),
      window.sessionStorage,
      NOW_MS,
    );

    expect(
      loadRetryableChatSends(NOW_MS, window.sessionStorage).get(
        operation.sessionId,
      ),
    ).toEqual(operation);
  });

  it('round-trips an explicit reasoning preference with the pending transcript', () => {
    const operation = buildOperation();
    operation.request.reasoning_preference = 'fast';
    operation.pendingTurn!.payload = { reasoning_preference: 'fast' };

    saveRetryableChatSends(
      new Map([[operation.sessionId, operation]]),
      window.sessionStorage,
      NOW_MS,
    );

    expect(
      loadRetryableChatSends(NOW_MS, window.sessionStorage).get(
        operation.sessionId,
      ),
    ).toEqual(operation);
  });

  it('rejects non-JSON attachment values instead of persisting File objects', () => {
    const operation = buildOperation();
    (operation.request.attachments?.[0] as Record<string, unknown>).file = (
      new File(['secret'], 'secret.txt', { type: 'text/plain' })
    );

    saveRetryableChatSends(
      new Map([[operation.sessionId, operation]]),
      window.sessionStorage,
      NOW_MS,
    );

    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it('removes expired operations', () => {
    const operation = buildOperation(0, NOW_MS - CHAT_RETRYABLE_SEND_TTL_MS - 1);
    window.sessionStorage.setItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: [operation],
      }),
    );

    expect(loadRetryableChatSends(
      NOW_MS,
      window.sessionStorage,
    )).toEqual(new Map());
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();
  });

  it('clears malformed or schema-incompatible data without throwing', () => {
    window.sessionStorage.setItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
      '{broken',
    );
    expect(() => loadRetryableChatSends(
      NOW_MS,
      window.sessionStorage,
    )).not.toThrow();
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();

    window.sessionStorage.setItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: [{ sessionId: 'missing-fields' }],
      }),
    );
    expect(loadRetryableChatSends(
      NOW_MS,
      window.sessionStorage,
    )).toEqual(new Map());
    expect(window.sessionStorage.getItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
    )).toBeNull();

    const validOperation = buildOperation();
    window.sessionStorage.setItem(
      CHAT_RETRYABLE_SEND_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: [
          { sessionId: 'missing-fields' },
          validOperation,
        ],
      }),
    );
    const salvaged = loadRetryableChatSends(
      NOW_MS,
      window.sessionStorage,
    );
    expect(salvaged.get(validOperation.sessionId)).toEqual(validOperation);
  });

  it('keeps only the newest bounded set of operations', () => {
    const operations = new Map(
      Array.from(
        { length: MAX_RETRYABLE_SENDS + 4 },
        (_, index) => {
          const operation = buildOperation(index);
          return [operation.sessionId, operation] as const;
        },
      ),
    );

    saveRetryableChatSends(
      operations,
      window.sessionStorage,
      NOW_MS + MAX_RETRYABLE_SENDS + 4,
    );
    const loaded = loadRetryableChatSends(
      NOW_MS + MAX_RETRYABLE_SENDS + 4,
      window.sessionStorage,
    );

    expect(loaded.size).toBe(MAX_RETRYABLE_SENDS);
    expect(loaded.has('session-0')).toBe(false);
    expect(loaded.has(`session-${MAX_RETRYABLE_SENDS + 3}`)).toBe(true);
  });

  it('persists bounded inline skill requests and clears expired data', () => {
    const operations = new Map(
      Array.from(
        { length: MAX_RETRYABLE_SENDS + 2 },
        (_, index) => {
          const operation = buildInlineSkillOperation(index);
          return [operation.retryKey, operation] as const;
        },
      ),
    );
    saveRetryableInlineSkillOperations(
      operations,
      window.sessionStorage,
      NOW_MS + MAX_RETRYABLE_SENDS + 2,
    );

    const loaded = loadRetryableInlineSkillOperations(
      NOW_MS + MAX_RETRYABLE_SENDS + 2,
      window.sessionStorage,
    );
    expect(loaded.size).toBe(MAX_RETRYABLE_SENDS);
    const newest = buildInlineSkillOperation(MAX_RETRYABLE_SENDS + 1);
    expect(loaded.get(newest.retryKey)?.request).toEqual(newest.request);

    const expired = buildInlineSkillOperation(
      99,
      NOW_MS - CHAT_RETRYABLE_SEND_TTL_MS - 1,
    );
    window.sessionStorage.setItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: [expired],
      }),
    );
    expect(loadRetryableInlineSkillOperations(
      NOW_MS,
      window.sessionStorage,
    )).toEqual(new Map());
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
  });

  it('clears malformed inline skill retry data without throwing', () => {
    window.sessionStorage.setItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
      JSON.stringify({
        version: CHAT_RETRYABLE_SEND_STORAGE_VERSION,
        operations: [{ retryKey: 'missing-fields' }],
      }),
    );

    expect(() => loadRetryableInlineSkillOperations(
      NOW_MS,
      window.sessionStorage,
    )).not.toThrow();
    expect(window.sessionStorage.getItem(
      INLINE_SKILL_RETRY_STORAGE_KEY,
    )).toBeNull();
  });

  it('keeps composer and inline skill retries independently', () => {
    const composerOperation = buildOperation();
    const inlineOperation = buildInlineSkillOperation();

    saveRetryableChatSends(
      new Map([[composerOperation.sessionId, composerOperation]]),
      window.sessionStorage,
      NOW_MS,
    );
    saveRetryableInlineSkillOperations(
      new Map([[inlineOperation.retryKey, inlineOperation]]),
      window.sessionStorage,
      NOW_MS,
    );

    expect(loadRetryableChatSends(
      NOW_MS,
      window.sessionStorage,
    ).get(composerOperation.sessionId)).toEqual(composerOperation);
    expect(loadRetryableInlineSkillOperations(
      NOW_MS,
      window.sessionStorage,
    ).get(inlineOperation.retryKey)).toEqual(inlineOperation);
  });

  it('deletes only the exact composer retry turn', () => {
    const first = buildOperation(1);
    const second = buildOperation(2);
    const operations = new Map([
      [first.sessionId, first],
      [second.sessionId, second],
    ]);

    expect(deleteRetryableChatSendForTurn(
      operations,
      first.sessionId,
      'different-turn',
    )).toBeNull();
    expect(operations.get(first.sessionId)).toBe(first);

    expect(deleteRetryableChatSendForTurn(
      operations,
      first.sessionId,
      first.turnId,
    )).toBe(first);
    expect(operations.has(first.sessionId)).toBe(false);
    expect(operations.get(second.sessionId)).toBe(second);
  });

  it('deletes composer retries only for the confirmed session', () => {
    const first = buildOperation(1);
    const second = buildOperation(2);
    const operations = new Map([
      [first.sessionId, first],
      [second.sessionId, second],
    ]);

    expect(deleteRetryableChatSendsForSession(
      operations,
      first.sessionId,
    )).toBe(first);
    expect(operations.has(first.sessionId)).toBe(false);
    expect(operations.get(second.sessionId)).toBe(second);
  });

  it('deletes exact inline retries without touching another turn', () => {
    const first = buildInlineSkillOperation(1);
    const sameTurn = {
      ...buildInlineSkillOperation(2),
      retryKey: JSON.stringify([
        first.request.session_id,
        null,
        'other-skill',
        [],
      ]),
      request: {
        ...buildInlineSkillOperation(2).request,
        session_id: first.request.session_id,
        client_turn_id: first.confirmation.turnId,
      },
      confirmation: {
        ...buildInlineSkillOperation(2).confirmation,
        sessionId: first.confirmation.sessionId,
        turnId: first.confirmation.turnId,
      },
    };
    const other = buildInlineSkillOperation(3);
    const operations = new Map([
      [first.retryKey, first],
      [sameTurn.retryKey, sameTurn],
      [other.retryKey, other],
    ]);

    expect(deleteRetryableInlineSkillOperationsForTurn(
      operations,
      String(first.request.session_id),
      'different-turn',
    )).toEqual([]);
    expect(deleteRetryableInlineSkillOperationsForTurn(
      operations,
      String(first.request.session_id),
      first.confirmation.turnId,
    )).toHaveLength(2);
    expect(operations.get(other.retryKey)).toBe(other);
  });

  it('deletes inline retries only for the confirmed session', () => {
    const first = buildInlineSkillOperation(1);
    const second = buildInlineSkillOperation(2);
    const operations = new Map([
      [first.retryKey, first],
      [second.retryKey, second],
    ]);

    expect(deleteRetryableInlineSkillOperationsForSession(
      operations,
      String(first.request.session_id),
    )).toEqual([first]);
    expect(operations.has(first.retryKey)).toBe(false);
    expect(operations.get(second.retryKey)).toBe(second);
  });
});
