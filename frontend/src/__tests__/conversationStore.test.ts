import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';
import { useChatTraceStore } from '@/stores/chat-trace';
import { useConversationStore } from '@/stores/conversation-store';

describe('conversation store', () => {
  beforeEach(() => {
    window.localStorage.clear();
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

  it('increments unread count once for inactive session message upserts', () => {
    const store = useConversationStore.getState();

    store.setCurrentSessionId('session-a');
    store.upsertMessage('session-b', {
      id: 'msg-b',
      messageId: 'msg-b',
      role: 'assistant',
      kind: 'assistant',
      content: 'done',
      timestamp: 2000,
      turnId: 'turn-b',
      messageKind: 'assistant_final',
    });
    store.upsertMessage('session-b', {
      id: 'msg-b',
      messageId: 'msg-b',
      role: 'assistant',
      kind: 'assistant',
      content: 'done',
      timestamp: 2000,
      turnId: 'turn-b',
      messageKind: 'assistant_final',
    });

    expect(useConversationStore.getState().unreadBySession['session-b']).toBe(1);
  });

  it('keeps existing sessions read on first session hydration', () => {
    const store = useConversationStore.getState();

    store.hydrateSessions([
      {
        session_id: 'session-a',
        title: 'Session A',
        last_message_preview: 'hello',
        last_user_message_preview: 'hello',
        title_overridden: false,
        last_timestamp: 10,
        message_count: 1,
        workspace_path: null,
      },
      {
        session_id: 'session-b',
        title: 'Session B',
        last_message_preview: 'older',
        last_user_message_preview: 'older',
        title_overridden: false,
        last_timestamp: 20,
        message_count: 4,
        workspace_path: null,
      },
    ], 'session-a');

    expect(useConversationStore.getState().unreadBySession).toEqual({
      'session-a': 0,
      'session-b': 0,
    });
  });

  it('restores unread counts from persisted read cursors on session hydration', () => {
    const store = useConversationStore.getState();

    store.hydrateSessions([
      {
        session_id: 'session-a',
        title: 'Session A',
        last_message_preview: 'hello',
        last_user_message_preview: 'hello',
        title_overridden: false,
        last_timestamp: 10,
        message_count: 1,
        workspace_path: null,
      },
      {
        session_id: 'session-b',
        title: 'Session B',
        last_message_preview: 'done',
        last_user_message_preview: 'ask',
        title_overridden: false,
        last_timestamp: 20,
        message_count: 2,
        workspace_path: null,
      },
    ], 'session-a');
    store.reset();

    store.hydrateSessions([
      {
        session_id: 'session-a',
        title: 'Session A',
        last_message_preview: 'hello',
        last_user_message_preview: 'hello',
        title_overridden: false,
        last_timestamp: 10,
        message_count: 1,
        workspace_path: null,
      },
      {
        session_id: 'session-b',
        title: 'Session B',
        last_message_preview: 'new answer',
        last_user_message_preview: 'ask',
        title_overridden: false,
        last_timestamp: 30,
        message_count: 4,
        workspace_path: null,
      },
    ], 'session-a');

    expect(useConversationStore.getState().unreadBySession['session-b']).toBe(2);
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

  it('does not switch sessions when background history or UX updates arrive', () => {
    const store = useConversationStore.getState();
    store.setCurrentSessionId('session-b');

    store.receiveHistory('session-a', [
      {
        id: 'msg-a',
        role: 'user',
        kind: 'user',
        content: 'hello from a',
        timestamp: 1000,
        turnId: 'turn-a',
      },
    ], 12);
    store.applyTurnUxPlan({
      sessionId: 'session-a',
      turnId: 'turn-a',
      uxPlan: {
        assistantSurfaceMode: 'final_only',
        interimText: 'working',
      },
    });

    const state = useConversationStore.getState();
    expect(state.currentSessionId).toBe('session-b');
    expect(state.messagesBySession['session-a']).toHaveLength(1);
    expect(state.messagesBySession['session-a']?.[0]?.content).toBe('hello from a');
  });

  it('counts newly recovered assistant history as unread in a background session', () => {
    const store = useConversationStore.getState();
    store.setCurrentSessionId('session-b');

    const history = [
      {
        id: 'msg-user-a',
        messageId: 'msg-user-a',
        role: 'user' as const,
        kind: 'user' as const,
        content: 'hello',
        timestamp: 1000,
        turnId: 'turn-a',
      },
      {
        id: 'msg-assistant-a',
        messageId: 'msg-assistant-a',
        role: 'assistant' as const,
        kind: 'assistant' as const,
        content: 'recovered answer',
        timestamp: 1001,
        turnId: 'turn-a',
        messageKind: 'assistant_final',
      },
    ];
    store.receiveHistory('session-a', history, 12);
    store.receiveHistory('session-a', history, 12);

    expect(useConversationStore.getState().currentSessionId).toBe('session-b');
    expect(useConversationStore.getState().unreadBySession['session-a']).toBe(1);
  });

  it('clears cached history versions on reset', () => {
    const store = useConversationStore.getState();

    store.receiveHistory('session-a', [], 3);
    store.reset();

    expect(useConversationStore.getState().historyVersionBySession).toEqual({});
  });

  it('clears one session history while keeping the session available', () => {
    const store = useConversationStore.getState();
    store.hydrateSessions([{
      session_id: 'session-a',
      title: 'Session A',
      last_message_preview: 'answer',
      last_user_message_preview: 'question',
      title_overridden: false,
      last_timestamp: 20,
      message_count: 2,
      workspace_path: null,
    }], 'session-a');
    store.receiveHistory('session-a', [{
      id: 'msg-a',
      messageId: 'msg-a',
      role: 'user',
      kind: 'user',
      content: 'question',
      timestamp: 20_000,
      turnId: 'turn-a',
    }], 7);

    store.clearSessionHistory('session-a');

    const state = useConversationStore.getState();
    expect(state.currentSessionId).toBe('session-a');
    expect(state.messagesBySession['session-a']).toEqual([]);
    expect(state.sessionsById['session-a']).toEqual(expect.objectContaining({
      last_message_preview: '',
      last_user_message_preview: '',
      last_timestamp: 0,
      message_count: 0,
    }));
    expect(state.historyVersionBySession['session-a']).toBe(8);
    expect(state.unreadBySession['session-a']).toBe(0);
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

  it('projects channel-delivery agent_response unconditionally (no lossy-delivery skip)', () => {
    // P3 Step 4: the lossy-channel-delivery special-case is removed. After
    // Steps 2-3 the channel-delivered ``agent_response`` always carries
    // ``turn_id`` (non-streamed) or is not sent at all (streamed turns finalize
    // via ``chat_message_upserted``), so the read side projects on ``session_id``
    // alone. A payload is therefore no longer silently skipped — it produces an
    // assistant bubble through the unconditional ``receiveAgentResponse``.
    const projected = applyRealtimeStoreProjection({
      event: 'agent_response',
      data: {
        session_id: 'session-channel',
        content: 'channel reply',
        is_final: true,
        timestamp: Date.now() / 1000,
        // no turn_id / no message_id — previously skipped, now projected.
      },
    });

    expect(projected).toBe(true);
    const messages = useConversationStore.getState().messagesBySession['session-channel'] || [];
    expect(messages.length).toBe(1);
    expect(messages[0]).toEqual(expect.objectContaining({
      role: 'assistant',
      content: 'channel reply',
    }));
  });

  it('still projects bubbles for richer agent_response payloads that carry turn_id or message_id', () => {
    // The realistic Step-3 shape: the channel-delivered agent_response carries
    // identity (turn_id + message_id), so the bubble projects with that identity.
    applyRealtimeStoreProjection({
      event: 'agent_response',
      data: {
        session_id: 'session-a',
        content: 'rich reply',
        timestamp: Date.now() / 1000,
        turn_id: 'turn-a',
        message_id: 'msg-a',
        message_kind: 'assistant_final',
      },
    });

    const message = useConversationStore.getState().messagesBySession['session-a']?.[0];
    expect(message).toEqual(expect.objectContaining({
      role: 'assistant',
      content: 'rich reply',
      messageId: 'msg-a',
      turnId: 'turn-a',
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

  it('trims trailing newlines when a streamed placeholder flushes locally', () => {
    const store = useConversationStore.getState();

    store.appendStreamTextDelta({
      sessionId: 'session-a',
      turnId: 'turn-a',
      textDelta: 'hello\n\n',
    });
    store.appendStreamTextFlush({
      sessionId: 'session-a',
      turnId: 'turn-a',
    });

    const message = useConversationStore.getState().messagesBySession['session-a']?.[0];

    expect(message).toEqual(expect.objectContaining({
      content: 'hello',
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

  it('anchors a late interim message to its original turn', () => {
    const store = useConversationStore.getState();

    store.appendPendingTurn({
      sessionId: 'session-a',
      input: '第一次架构扫描',
      turnId: 'turn-first',
      timestamp: 1000,
      pendingLabel: 'Thinking...',
    });
    store.appendPendingTurn({
      sessionId: 'session-a',
      input: '第二次架构扫描',
      turnId: 'turn-second',
      timestamp: 2000,
      pendingLabel: 'Thinking...',
    });
    store.upsertMessage('session-a', {
      id: 'msg-first-interim',
      messageId: 'msg-first-interim',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'assistant_interim',
      content: '我看一下。',
      timestamp: 3000,
      turnId: 'turn-first',
    });
    store.upsertMessage('session-a', {
      id: 'msg-first-interim',
      messageId: 'msg-first-interim',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'assistant_interim',
      content: '已取消执行',
      timestamp: 4000,
      turnId: 'turn-first',
    });

    const messages = useConversationStore.getState().messagesBySession['session-a'] || [];

    expect(messages.map((message) => [message.turnId, message.role, message.messageKind || null])).toEqual([
      ['turn-first', 'user', null],
      ['turn-first', 'assistant', 'assistant_interim'],
      ['turn-second', 'user', null],
    ]);
    expect(messages[1].content).toBe('已取消执行');
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

  it('routes tool-call assistant narration into runtime status updates', () => {
    applyRealtimeStoreProjection({
      event: 'agent_response_chunk',
      data: {
        session_id: 'session-a',
        turn_id: 'turn-status',
        persona_id: 'persona-seven',
        event: {
          kind: 'status_update',
          text: '附件解析失败了，我先尝试其它提取方式。',
          source: 'assistant_tool_call',
          step_label: 'tool_call_narration',
        },
      },
    });

    const statusMessage = (useConversationStore.getState().messagesBySession['session-a'] || [])
      .find((message) => message.turnId === 'turn-status' && message.role === 'assistant');

    expect(statusMessage).toEqual(expect.objectContaining({
      turnId: 'turn-status',
      role: 'assistant',
      streaming: true,
      personaId: 'persona-seven',
      runtimeStatuses: [
        expect.objectContaining({
          source: 'assistant_tool_call',
          stepLabel: 'tool_call_narration',
          content: '附件解析失败了，我先尝试其它提取方式。',
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
