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
});
