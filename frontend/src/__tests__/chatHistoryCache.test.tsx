import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { messagesApi } from '@/api';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import { normalizeHistoryMessages } from '@/domain/chat/state';
import { useChatSessionLifecycle } from '@/hooks/useChatSessionLifecycle';
import { useConversationStore } from '@/stores/conversation-store';

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getHistory: vi.fn(),
  },
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/personas', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/personas')>('@/api/modules/personas');
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      list: vi.fn(),
      getGreeting: vi.fn(),
      bootstrapInit: vi.fn(),
    },
  };
});

const Harness = ({ sessionId }: { sessionId: string }) => {
  useChatSessionLifecycle({
    currentSessionId: sessionId,
    upsertMessage: useConversationStore.getState().upsertMessage,
    removeMessage: useConversationStore.getState().removeMessage,
    translate: (key: string) => key,
  });
  return null;
};

describe('chat history cache', () => {
  beforeEach(() => {
    useConversationStore.getState().reset();
    vi.mocked(configApi.get).mockReset().mockResolvedValue({ data: DEFAULT_SYSTEM_CONFIG } as any);
    vi.mocked(personasApi.list).mockReset().mockResolvedValue({ success: true, data: [] } as any);
    vi.mocked(personasApi.getGreeting).mockReset().mockResolvedValue({
      success: true,
      data: { name: 'AI', avatar: '', needs_bootstrap: false },
    } as any);
    vi.mocked(personasApi.bootstrapInit).mockReset().mockResolvedValue({
      success: true,
      data: { bootstrap_active: false, opening: null },
    } as any);
    vi.mocked(messagesApi.getHistory).mockReset().mockResolvedValue({
      user_id: 'local_user',
      session_id: 'session-a',
      messages: [],
      count: 0,
      history_version: 1,
    } as any);
  });

  afterEach(() => {
    cleanup();
    useConversationStore.getState().reset();
  });

  it('skips history fetch when cached messages match the session history version', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-a',
        title: 'Session A',
        last_message_preview: 'cached',
        last_user_message_preview: 'hello',
        title_overridden: false,
        last_timestamp: 1000,
        message_count: 1,
        workspace_path: null,
        history_version: 5,
      },
    ], 'session-a');
    useConversationStore.getState().receiveHistory(
      'session-a',
      normalizeHistoryMessages([
        { role: 'user', kind: 'user', content: 'hello', timestamp: 1000, turn_id: 'turn-a' },
      ] as any),
      5,
    );

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(personasApi.list).toHaveBeenCalled());
    expect(messagesApi.getHistory).not.toHaveBeenCalled();
  });

  it('fetches history when the session history version changes', async () => {
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'session-a',
        title: 'Session A',
        last_message_preview: 'newer',
        last_user_message_preview: 'hello',
        title_overridden: false,
        last_timestamp: 1000,
        message_count: 1,
        workspace_path: null,
        history_version: 6,
      },
    ], 'session-a');
    useConversationStore.getState().receiveHistory('session-a', [], 5);

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', 'session-a'));
  });
});
