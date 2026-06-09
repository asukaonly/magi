import { cleanup, render, waitFor } from '@testing-library/react';
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
    setCurrentSessionId: vi.fn(),
    resetConversation: vi.fn(),
    resetTraceDrawer: vi.fn(),
    upsertMessage: useConversationStore.getState().upsertMessage,
    removeMessage: useConversationStore.getState().removeMessage,
    translate: (key: string) => key,
  });
  return null;
};

describe('shouldFireBootstrap', () => {
  it('fires only when bootstrap is needed AND the tour is loaded AND completed', () => {
    expect(shouldFireBootstrap({ needsBootstrap: true, tourLoaded: true, tourCompleted: true })).toBe(true);
  });

  it('holds while the tour is still pending (loaded but not completed)', () => {
    expect(shouldFireBootstrap({ needsBootstrap: true, tourLoaded: true, tourCompleted: false })).toBe(false);
  });

  it('holds until the tour state is known (not yet loaded)', () => {
    expect(shouldFireBootstrap({ needsBootstrap: true, tourLoaded: false, tourCompleted: true })).toBe(false);
  });

  it('never fires when bootstrap is not needed', () => {
    expect(shouldFireBootstrap({ needsBootstrap: false, tourLoaded: true, tourCompleted: true })).toBe(false);
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
