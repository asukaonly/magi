import { beforeEach, describe, expect, it } from 'vitest';
import { useConversationStore } from '@/stores/conversation-store';

describe('conversation store', () => {
  beforeEach(() => {
    useConversationStore.getState().reset();
  });

  it('increments unread count for inactive sessions on agent response', () => {
    const store = useConversationStore.getState();

    store.setCurrentSessionId('session-a');
    store.receiveAgentResponse({
      sessionId: 'session-b',
      content: 'hello',
      timestamp: Date.now(),
      turnId: 'turn-b',
    });

    expect(useConversationStore.getState().unreadBySession['session-b']).toBe(1);
  });

  it('clears unread count when a session becomes active', () => {
    const store = useConversationStore.getState();

    store.receiveAgentResponse({
      sessionId: 'session-b',
      content: 'hello',
      timestamp: Date.now(),
      turnId: 'turn-b',
    });
    store.receiveAgentResponse({
      sessionId: 'session-b',
      content: 'again',
      timestamp: Date.now() + 1,
      turnId: 'turn-c',
    });

    store.setCurrentSessionId('session-b');

    expect(useConversationStore.getState().unreadBySession['session-b']).toBe(0);
  });

  it('keeps the locally selected session when session summaries refresh from the server', () => {
    const store = useConversationStore.getState();

    store.setCurrentSessionId('session-b');
    store.hydrateSessions(
      [
        {
          session_id: 'session-a',
          title: 'Session A',
          last_message_preview: 'older',
          last_timestamp: 10,
          message_count: 1,
        },
        {
          session_id: 'session-b',
          title: 'Session B',
          last_message_preview: 'selected',
          last_timestamp: 11,
          message_count: 2,
        },
      ],
      'session-a'
    );

    expect(useConversationStore.getState().currentSessionId).toBe('session-b');
  });

  it('falls back to the newest available session when no preferred selection exists', () => {
    const store = useConversationStore.getState();

    store.setCurrentSessionId(null);
    store.hydrateSessions([
      {
        session_id: 'session-a',
        title: 'Session A',
        last_message_preview: 'older',
        last_timestamp: 10,
        message_count: 1,
      },
      {
        session_id: 'session-b',
        title: 'Session B',
        last_message_preview: 'newer',
        last_timestamp: 11,
        message_count: 2,
      },
    ]);

    expect(useConversationStore.getState().currentSessionId).toBe('session-a');
  });

  it('keeps the richer local final answer when a history refresh only returns a status placeholder', () => {
    const store = useConversationStore.getState();

    store.receiveHistory('session-a', [
      {
        id: 'turn-1-user',
        role: 'user',
        kind: 'user',
        content: 'question',
        timestamp: 1000,
        turnId: 'turn-1',
      },
      {
        id: 'turn-1-status',
        role: 'assistant',
        kind: 'status',
        content: 'Tool chain completed',
        timestamp: 1001,
        turnId: 'turn-1',
        traceAvailable: true,
      },
    ]);

    store.receiveAgentResponse({
      sessionId: 'session-a',
      content: 'final answer',
      timestamp: 1002,
      turnId: 'turn-1',
    });

    store.receiveHistory('session-a', [
      {
        id: 'turn-1-user-refresh',
        role: 'user',
        kind: 'user',
        content: 'question',
        timestamp: 1000,
        turnId: 'turn-1',
      },
      {
        id: 'turn-1-status-refresh',
        role: 'assistant',
        kind: 'status',
        content: 'Tool chain completed',
        timestamp: 1001,
        turnId: 'turn-1',
        traceAvailable: true,
      },
    ]);

    expect(useConversationStore.getState().messagesBySession['session-a']).toEqual([
      expect.objectContaining({
        id: 'turn-1-user-refresh',
        role: 'user',
        kind: 'user',
        content: 'question',
        timestamp: 1000,
        turnId: 'turn-1',
      }),
      expect.objectContaining({
        id: 'turn-1-status-refresh',
        role: 'assistant',
        kind: 'status',
        content: 'Tool chain completed',
        timestamp: 1001,
        turnId: 'turn-1',
        traceAvailable: true,
      }),
      expect.objectContaining({
        role: 'assistant',
        kind: 'assistant',
        content: 'final answer',
        turnId: 'turn-1',
        messageKind: 'assistant_final',
      }),
    ]);
  });

  it('merges a durable user message into the local pending reply without dropping the quote', () => {
    const store = useConversationStore.getState();

    store.appendPendingTurn({
      sessionId: 'session-a',
      input: 'Follow-up question',
      turnId: 'turn-reply',
      timestamp: 1000,
      pendingLabel: 'Thinking...',
      replyTo: {
        messageId: 'msg-root',
        role: 'assistant',
        messageKind: 'assistant_final',
        contentExcerpt: 'Root answer',
      },
    });

    store.upsertMessage('session-a', {
      id: 'msg-user-reply',
      role: 'user',
      kind: 'user',
      content: 'Follow-up question',
      timestamp: 1000,
      messageId: 'msg-user-reply',
      messageKind: 'user_text',
      turnId: 'turn-reply',
      replyTo: {
        messageId: 'msg-root',
        role: 'assistant',
        messageKind: 'assistant_final',
        contentExcerpt: 'Root answer',
      },
    });

    const mergedReply = useConversationStore.getState().messagesBySession['session-a']
      ?.find((message) => message.turnId === 'turn-reply' && message.role === 'user');

    expect(mergedReply).toEqual(expect.objectContaining({
      id: 'msg-user-reply',
      messageId: 'msg-user-reply',
      turnId: 'turn-reply',
      content: 'Follow-up question',
      replyTo: {
        messageId: 'msg-root',
        role: 'assistant',
        messageKind: 'assistant_final',
        contentExcerpt: 'Root answer',
      },
    }));
  });
});
