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
      response: 'hello',
      timestamp: Date.now(),
      turnId: 'turn-b',
    });

    expect(useConversationStore.getState().unreadBySession['session-b']).toBe(1);
  });

  it('clears unread count when a session becomes active', () => {
    const store = useConversationStore.getState();

    store.receiveAgentResponse({
      sessionId: 'session-b',
      response: 'hello',
      timestamp: Date.now(),
      turnId: 'turn-b',
    });
    store.receiveAgentResponse({
      sessionId: 'session-b',
      response: 'again',
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
});
