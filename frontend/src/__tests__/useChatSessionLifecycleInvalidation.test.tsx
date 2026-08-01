import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearPersistedChatRetriesForTurn } from '@/hooks/chatRetryLifecycle';
import { dispatchAppEvent } from '@/constants/events';
import { useChatSessionLifecycle } from '@/hooks/useChatSessionLifecycle';
import { useConversationStore } from '@/stores/conversation-store';

const {
  getHistoryMock,
  configGetMock,
  listPersonasMock,
  getGreetingMock,
} = vi.hoisted(() => ({
  getHistoryMock: vi.fn(),
  configGetMock: vi.fn(),
  listPersonasMock: vi.fn(),
  getGreetingMock: vi.fn(),
}));

vi.mock('@/api', () => ({
  messagesApi: {
    getHistory: getHistoryMock,
  },
}));

vi.mock('@/api/modules/config', () => ({
  configApi: {
    get: configGetMock,
  },
}));

vi.mock('@/api/modules/personas', () => ({
  personasApi: {
    list: listPersonasMock,
    getGreeting: getGreetingMock,
    bootstrapInit: vi.fn(),
  },
}));

vi.mock('@/hooks/useProductTourFlag', () => ({
  useProductTourFlag: () => ({
    completed: false,
    loaded: true,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
};

describe('useChatSessionLifecycle destructive invalidation', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    useConversationStore.getState().reset();
    configGetMock.mockReset().mockResolvedValue({ data: {} });
    listPersonasMock.mockReset().mockResolvedValue({ success: true, data: [] });
    getGreetingMock.mockReset().mockResolvedValue({
      success: true,
      data: { name: 'AI', greeting: '', needs_bootstrap: false },
    });
    getHistoryMock.mockReset();
  });

  it('does not restore a deleted turn from a history request that started earlier', async () => {
    const historyRequest = createDeferred<{
      user_id: string;
      session_id: string;
      messages: Array<Record<string, unknown>>;
      count: number;
    }>();
    getHistoryMock.mockReturnValue(historyRequest.promise);
    const hook = renderHook(() => useChatSessionLifecycle({
      currentSessionId: 'session-1',
      upsertMessage: useConversationStore.getState().upsertMessage,
      removeMessage: useConversationStore.getState().removeMessage,
      translate: (key) => key,
    }));
    const pending = hook.result.current.ensureSessionHistoryReady('session-1');

    clearPersistedChatRetriesForTurn('session-1', 'turn-old');
    await act(async () => {
      historyRequest.resolve({
        user_id: 'local_user',
        session_id: 'session-1',
        messages: [{
          message_id: 'message-old',
          role: 'user',
          content: 'Deleted content',
          timestamp: 1,
          turn_id: 'turn-old',
          kind: 'user',
        }],
        count: 1,
      });
      expect(await pending).toMatchObject({ loaded: false });
    });

    expect(useConversationStore.getState().messagesBySession['session-1']).toBeUndefined();
  });

  it('does not restore history whose response arrives after a full clear starts', async () => {
    const historyRequest = createDeferred<{
      user_id: string;
      session_id: string;
      messages: Array<Record<string, unknown>>;
      count: number;
    }>();
    getHistoryMock.mockReturnValue(historyRequest.promise);
    const hook = renderHook(() => useChatSessionLifecycle({
      currentSessionId: 'session-1',
      upsertMessage: useConversationStore.getState().upsertMessage,
      removeMessage: useConversationStore.getState().removeMessage,
      translate: (key) => key,
    }));
    const pending = hook.result.current.ensureSessionHistoryReady('session-1');

    act(() => {
      dispatchAppEvent.memoryClearStarted();
    });
    await act(async () => {
      historyRequest.resolve({
        user_id: 'local_user',
        session_id: 'session-1',
        messages: [{
          message_id: 'message-old',
          role: 'user',
          content: 'Content from before the clear',
          timestamp: 1,
          turn_id: 'turn-old',
          kind: 'user',
        }],
        count: 1,
      });
      expect(await pending).toMatchObject({ loaded: false });
    });

    expect(useConversationStore.getState().messagesBySession['session-1']).toBeUndefined();
  });
});
