import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { messagesApi } from '@/api';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { personasApi } from '@/api/modules/personas';
import { DEFAULT_USER_ID } from '@/constants';
import {
  shouldFireBootstrap,
  useChatSessionLifecycle,
} from '@/hooks/useChatSessionLifecycle';
import { useProductTourFlag } from '@/hooks/useProductTourFlag';
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

vi.mock('@/hooks/useProductTourFlag', () => ({
  useProductTourFlag: vi.fn(),
}));

const Harness = ({ sessionId }: { sessionId: string }) => {
  useChatSessionLifecycle({
    currentSessionId: sessionId,
    upsertMessage: useConversationStore.getState().upsertMessage,
    removeMessage: useConversationStore.getState().removeMessage,
    translate: (key: string) => key,
  });
  return null;
};

describe('shouldFireBootstrap', () => {
  it('fires only when bootstrap is needed AND the tour is loaded AND completed', () => {
    expect(shouldFireBootstrap({
      needsBootstrap: true,
      tourLoaded: true,
      tourCompleted: true,
      historyLoaded: true,
      hasUserMessage: false,
    })).toBe(true);
  });

  it('holds while the tour is still pending (loaded but not completed)', () => {
    expect(shouldFireBootstrap({
      needsBootstrap: true,
      tourLoaded: true,
      tourCompleted: false,
      historyLoaded: true,
      hasUserMessage: false,
    })).toBe(false);
  });

  it('holds until the tour state is known (not yet loaded)', () => {
    expect(shouldFireBootstrap({
      needsBootstrap: true,
      tourLoaded: false,
      tourCompleted: true,
      historyLoaded: true,
      hasUserMessage: false,
    })).toBe(false);
  });

  it('never fires when bootstrap is not needed', () => {
    expect(shouldFireBootstrap({
      needsBootstrap: false,
      tourLoaded: true,
      tourCompleted: true,
      historyLoaded: true,
      hasUserMessage: false,
    })).toBe(false);
  });

  it('holds until history is loaded', () => {
    expect(shouldFireBootstrap({
      needsBootstrap: true,
      tourLoaded: true,
      tourCompleted: true,
      historyLoaded: false,
      hasUserMessage: false,
    })).toBe(false);
  });

  it('never fires when history already contains a user message', () => {
    expect(shouldFireBootstrap({
      needsBootstrap: true,
      tourLoaded: true,
      tourCompleted: true,
      historyLoaded: true,
      hasUserMessage: true,
    })).toBe(false);
  });
});

describe('bootstrap defer gate (hook integration)', () => {
  beforeEach(() => {
    useConversationStore.getState().reset();
    vi.mocked(configApi.get).mockReset().mockResolvedValue({ data: DEFAULT_SYSTEM_CONFIG } as any);
    vi.mocked(personasApi.list).mockReset().mockResolvedValue({ success: true, data: [] } as any);
    vi.mocked(personasApi.getGreeting).mockReset().mockResolvedValue({
      success: true,
      data: { name: 'AI', avatar: '', needs_bootstrap_init: true },
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
    vi.mocked(useProductTourFlag).mockReset();
  });

  afterEach(() => {
    cleanup();
    useConversationStore.getState().reset();
  });

  it('does not bootstrap while the product tour is pending', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: false,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);

    render(<Harness sessionId="session-a" />);

    // Greeting is fetched (so needs_bootstrap is known) but bootstrapInit is gated.
    await waitFor(() => expect(personasApi.getGreeting).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();
  });

  it('does not bootstrap until the tour state is loaded', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: false,
      markCompleted: vi.fn(),
    } as any);

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(personasApi.getGreeting).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();
  });

  it('bootstraps once the tour is resolved (loaded + completed)', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(personasApi.bootstrapInit).toHaveBeenCalledWith('session-a', DEFAULT_USER_ID));
  });

  it('waits for history and skips bootstrap when a user message already exists', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);

    let resolveHistory: ((value: unknown) => void) | null = null;
    vi.mocked(messagesApi.getHistory).mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveHistory = resolve;
      }) as any,
    );

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(messagesApi.getHistory).toHaveBeenCalledWith(DEFAULT_USER_ID, 'session-a'));
    await waitFor(() => expect(personasApi.getGreeting).toHaveBeenCalled());
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();

    act(() => {
      resolveHistory?.({
        user_id: DEFAULT_USER_ID,
        session_id: 'session-a',
        messages: [
          {
            message_id: 'message-1',
            role: 'user',
            kind: 'user',
            content: 'A real first message',
            timestamp: 1,
            turn_id: 'turn-1',
          },
        ],
        count: 1,
        history_version: 2,
      });
    });

    await waitFor(() => {
      expect(useConversationStore.getState().messagesBySession['session-a']).toEqual([
        expect.objectContaining({ role: 'user', content: 'A real first message' }),
      ]);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();
  });

  it('does not risk bootstrap when history cannot be loaded', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);
    vi.mocked(messagesApi.getHistory).mockRejectedValue(new Error('history unavailable'));

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(personasApi.getGreeting).toHaveBeenCalled());
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 250));
    });
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(2);
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();
  });

  it('retries a transient history failure before deciding whether to bootstrap', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);
    vi.mocked(messagesApi.getHistory)
      .mockRejectedValueOnce(new Error('temporary history failure'))
      .mockResolvedValueOnce({
        user_id: DEFAULT_USER_ID,
        session_id: 'session-a',
        messages: [],
        count: 0,
        history_version: 1,
      } as any);

    render(<Harness sessionId="session-a" />);

    await waitFor(() => expect(personasApi.bootstrapInit).toHaveBeenCalledWith(
      'session-a',
      DEFAULT_USER_ID,
    ));
    expect(vi.mocked(messagesApi.getHistory).mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(vi.mocked(messagesApi.getHistory).mock.invocationCallOrder[1]).toBeLessThan(
      vi.mocked(personasApi.bootstrapInit).mock.invocationCallOrder[0],
    );
  });

  it('keeps recovering history in the background after the initial attempts fail', async () => {
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);
    vi.mocked(messagesApi.getHistory)
      .mockRejectedValueOnce(new Error('history temporarily unavailable'))
      .mockRejectedValueOnce(new Error('history still unavailable'))
      .mockResolvedValueOnce({
        user_id: DEFAULT_USER_ID,
        session_id: 'session-a',
        messages: [{
          message_id: 'message-1',
          role: 'user',
          kind: 'user',
          content: 'Recovered first answer',
          timestamp: 1,
          turn_id: 'turn-1',
        }],
        count: 1,
        history_version: 2,
      } as any);

    render(<Harness sessionId="session-a" />);

    await waitFor(() => {
      expect(
        useConversationStore.getState().messagesBySession['session-a'],
      ).toEqual([
        expect.objectContaining({ content: 'Recovered first answer' }),
      ]);
    }, { timeout: 2_000 });
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(3);
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();
  });

  it('re-fires the deferred bootstrap when the tour flips from pending to completed', async () => {
    // First render: tour pending -> no bootstrap.
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: false,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);

    const { rerender } = render(<Harness sessionId="session-a" />);
    await waitFor(() => expect(personasApi.getGreeting).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(personasApi.bootstrapInit).not.toHaveBeenCalled();

    // Tour completes -> the gate opens and the bootstrap effect must re-fire.
    vi.mocked(useProductTourFlag).mockReturnValue({
      completed: true,
      loaded: true,
      markCompleted: vi.fn(),
    } as any);
    rerender(<Harness sessionId="session-a" />);

    await waitFor(() => expect(personasApi.bootstrapInit).toHaveBeenCalledWith('session-a', DEFAULT_USER_ID));
  });
});
