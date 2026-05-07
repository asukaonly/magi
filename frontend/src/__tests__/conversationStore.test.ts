import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import { useChatTraceStore } from '@/stores/chat-trace';
import { useConversationStore } from '@/stores/conversation-store';

describe('conversation store', () => {
  beforeEach(() => {
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
  });

  afterEach(() => {
    useConversationStore.getState().reset();
    useChatTraceStore.getState().reset();
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

  it('records the history version for received session history', () => {
    const store = useConversationStore.getState();

    store.receiveHistory('session-a', [
      {
        id: 'msg-a',
        role: 'user',
        kind: 'user',
        content: 'hello',
        timestamp: 1000,
        turnId: 'turn-a',
      },
    ], 12);

    expect(useConversationStore.getState().historyVersionBySession['session-a']).toBe(12);
  });

  it('clears cached history versions on reset', () => {
    const store = useConversationStore.getState();

    store.receiveHistory('session-a', [], 3);
    store.reset();

    expect(useConversationStore.getState().historyVersionBySession).toEqual({});
  });

  it('keeps local ask transcript messages across history refreshes', () => {
    const store = useConversationStore.getState();

    store.upsertMessage('session-a', {
      id: 'ask:ask-1',
      messageId: 'ask:ask-1',
      role: 'assistant',
      kind: 'assistant',
      content: 'Which branch should I use?',
      timestamp: 1000,
      messageKind: 'ask_request',
      payload: {
        ask_request_id: 'ask-1',
        status: 'answered',
      },
    });
    store.upsertMessage('session-a', {
      id: 'ask-response:ask-1',
      messageId: 'ask-response:ask-1',
      role: 'user',
      kind: 'user',
      content: 'main',
      timestamp: 1001,
      messageKind: 'ask_response',
      payload: {
        ask_request_id: 'ask-1',
      },
    });

    store.receiveHistory('session-a', [], 4);

    const messages = useConversationStore.getState().messagesBySession['session-a'] || [];
    expect(messages.map((message) => message.messageKind)).toEqual(['ask_request', 'ask_response']);
  });

  it('stores persona identity from realtime agent responses', () => {
    applyRealtimeStoreProjection({
      event: 'agent_response',
      data: {
        session_id: 'session-a',
        content: 'hello from seven',
        timestamp: Date.now() / 1000,
        turn_id: 'turn-a',
        message_id: 'msg-a',
        message_kind: 'assistant_final',
        persona_id: 'persona-seven',
      },
    });

    const message = useConversationStore.getState().messagesBySession['session-a']?.[0];

    expect(message).toEqual(expect.objectContaining({
      role: 'assistant',
      content: 'hello from seven',
      personaId: 'persona-seven',
    }));
  });

  it('projects assistant attachments from realtime agent responses', () => {
    applyRealtimeStoreProjection({
      event: 'agent_response',
      data: {
        session_id: 'session-a',
        content: '图片已生成',
        timestamp: Date.now() / 1000,
        turn_id: 'turn-a',
        message_id: 'msg-a',
        message_kind: 'assistant_final',
        attachments: [
          {
            attachment_id: 'att-a',
            kind: 'image',
            original_name: 'generated.png',
            size_bytes: 1024,
          },
        ],
      },
    });

    const message = useConversationStore.getState().messagesBySession['session-a']?.[0];

    expect(message).toEqual(expect.objectContaining({
      attachments: [
        expect.objectContaining({
          attachment_id: 'att-a',
          kind: 'image',
          original_name: 'generated.png',
        }),
      ],
    }));
  });

  it('accepts trace update invalidations without summaries', () => {
    const projected = applyRealtimeStoreProjection({
      event: 'execution_trace_update',
      data: {
        session_id: 'session-a',
        turn_id: 'turn-a',
        refresh_trace: true,
      },
    });

    expect(projected).toBe(true);
    expect(useChatTraceStore.getState().summaries).toEqual({});
    expect(useConversationStore.getState().messagesBySession).toEqual({});
  });

  it('preserves persona identity when later realtime updates omit it', () => {
    const store = useConversationStore.getState();

    store.receiveAgentResponse({
      sessionId: 'session-a',
      content: 'draft',
      timestamp: Date.now(),
      turnId: 'turn-a',
      messageId: 'msg-a',
      messageKind: 'assistant_final',
      personaId: 'persona-seven',
    });
    store.receiveAgentResponse({
      sessionId: 'session-a',
      content: 'updated',
      timestamp: Date.now() + 1,
      turnId: 'turn-a',
      messageId: 'msg-a',
      messageKind: 'assistant_final',
    });

    const message = useConversationStore.getState().messagesBySession['session-a']?.[0];

    expect(message).toEqual(expect.objectContaining({
      content: 'updated',
      personaId: 'persona-seven',
    }));
  });

  it('stores persona identity on streaming assistant placeholders', () => {
    const store = useConversationStore.getState();

    store.appendStreamTextDelta({
      sessionId: 'session-a',
      turnId: 'turn-a',
      personaId: 'persona-seven',
      textDelta: 'hel',
    });
    store.appendStreamTextDelta({
      sessionId: 'session-a',
      turnId: 'turn-a',
      textDelta: 'lo',
    });
    store.appendStreamTextFlush({
      sessionId: 'session-a',
      turnId: 'turn-a',
    });

    const message = useConversationStore.getState().messagesBySession['session-a']?.[0];

    expect(message).toEqual(expect.objectContaining({
      content: 'hello',
      personaId: 'persona-seven',
      streaming: false,
    }));
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

  it('keeps persisted interim, todo, and final messages together after history rehydration', () => {
    const store = useConversationStore.getState();

    store.receiveHistory('session-a', [
      {
        id: 'msg-user',
        messageId: 'msg-user',
        role: 'user',
        kind: 'user',
        messageKind: 'user_text',
        content: '详细分析下',
        timestamp: 1000,
        turnId: 'turn-history',
      },
      {
        id: 'msg-interim',
        messageId: 'msg-interim',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_interim',
        content: '让我仔细想想再回复你。',
        timestamp: 1010,
        turnId: 'turn-history',
      },
      {
        id: 'msg-todo',
        messageId: 'msg-todo',
        role: 'assistant',
        kind: 'status',
        messageKind: 'todo_state',
        content: 'Inspect runtime drift\nPatch UI',
        timestamp: 1020,
        turnId: 'turn-history',
        payload: {
          items: [
            { id: 'todo-1', content: 'Inspect runtime drift', status: 'in_progress' },
            { id: 'todo-2', content: 'Patch UI', status: 'completed' },
          ],
        },
      },
      {
        id: 'msg-final',
        messageId: 'msg-final',
        role: 'assistant',
        kind: 'assistant',
        messageKind: 'assistant_final',
        content: '最终结论。',
        timestamp: 1030,
        turnId: 'turn-history',
      },
    ]);

    const turnMessages = (useConversationStore.getState().messagesBySession['session-a'] || [])
      .filter((message) => message.turnId === 'turn-history');

    expect(turnMessages).toEqual([
      expect.objectContaining({
        id: 'msg-user',
        messageKind: 'user_text',
        turnId: 'turn-history',
      }),
      expect.objectContaining({
        id: 'msg-interim',
        messageKind: 'assistant_interim',
        turnId: 'turn-history',
      }),
      expect.objectContaining({
        id: 'msg-todo',
        kind: 'status',
        messageKind: 'todo_state',
        turnId: 'turn-history',
      }),
      expect.objectContaining({
        id: 'msg-final',
        messageKind: 'assistant_final',
        turnId: 'turn-history',
      }),
    ]);

  });

  it('preserves assistant attachments from realtime agent responses', () => {
    const store = useConversationStore.getState();

    store.receiveAgentResponse({
      sessionId: 'session-a',
      content: '照片已准备好',
      attachments: [
        {
          attachment_id: 'att-photo-1',
          kind: 'image',
          original_name: 'hangzhou.jpg',
          size_bytes: 2048,
        },
      ],
      timestamp: Date.now(),
      turnId: 'turn-photo',
      messageId: 'msg-photo-final',
      messageKind: 'assistant_final',
    });

    expect(
      useConversationStore.getState().messagesBySession['session-a']?.find((message) => message.turnId === 'turn-photo')
    ).toEqual(
      expect.objectContaining({
        role: 'assistant',
        kind: 'assistant',
        content: '照片已准备好',
        turnId: 'turn-photo',
        messageId: 'msg-photo-final',
        attachments: [
          expect.objectContaining({
            attachment_id: 'att-photo-1',
            kind: 'image',
            original_name: 'hangzhou.jpg',
          }),
        ],
      })
    );
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

  it('tracks tool-call progress on the streaming assistant message for a turn', () => {
    const store = useConversationStore.getState();

    store.appendStreamToolCall({
      sessionId: 'session-a',
      turnId: 'turn-tools',
      toolCallId: 'call-1',
      toolName: 'web-search',
      status: 'running',
    });
    store.appendStreamToolCall({
      sessionId: 'session-a',
      turnId: 'turn-tools',
      toolCallId: 'call-1',
      toolArgsDelta: '{"query":"magi"}',
      status: 'running',
    });
    store.appendStreamToolCall({
      sessionId: 'session-a',
      turnId: 'turn-tools',
      toolCallId: 'call-1',
      toolName: 'web-search',
      toolArguments: { query: 'magi' },
      status: 'completed',
    });

    const toolMessage = (useConversationStore.getState().messagesBySession['session-a'] || [])
      .find((message) => message.turnId === 'turn-tools' && message.role === 'assistant');

    expect(toolMessage).toEqual(expect.objectContaining({
      turnId: 'turn-tools',
      role: 'assistant',
      streaming: true,
      toolCalls: [
        expect.objectContaining({
          toolCallId: 'call-1',
          toolName: 'web-search',
          status: 'completed',
          toolArgsText: '{"query":"magi"}',
          toolArguments: { query: 'magi' },
        }),
      ],
    }));
  });

  it('does not merge streaming runtime placeholders into todo state messages', () => {
    const store = useConversationStore.getState();

    store.appendStreamToolCall({
      sessionId: 'session-a',
      turnId: 'turn-tools',
      toolCallId: 'call-1',
      toolName: 'web-search',
      status: 'running',
    });

    store.receiveHistory('session-a', [
      {
        id: 'msg-todo',
        messageId: 'msg-todo',
        role: 'assistant',
        kind: 'status',
        messageKind: 'todo_state',
        content: 'Search official sources',
        timestamp: 2000,
        turnId: 'turn-tools',
        payload: {
          items: [
            { id: 'task-1', content: 'Search official sources', status: 'in_progress' },
          ],
        },
      },
    ]);

    const messages = useConversationStore.getState().messagesBySession['session-a'] || [];
    const runtimeMessage = messages.find(
      (message) => message.turnId === 'turn-tools' && message.kind === 'assistant' && !message.messageId,
    );
    const todoMessage = messages.find((message) => message.messageKind === 'todo_state');

    expect(runtimeMessage).toEqual(expect.objectContaining({
      streaming: true,
      toolCalls: [expect.objectContaining({ toolName: 'web-search' })],
    }));
    expect(todoMessage).toEqual(expect.objectContaining({
      messageId: 'msg-todo',
      kind: 'status',
      messageKind: 'todo_state',
    }));
  });
});
