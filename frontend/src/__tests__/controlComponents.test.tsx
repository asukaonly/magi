/**
 * Smoke tests for the control-plane components.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PermissionModal } from '@/components/control/PermissionModal';
import { AskDialog } from '@/components/control/AskDialog';
import { PermissionModalHost } from '@/components/control/PermissionModalHost';
import { dispatchAppEvent } from '@/constants/events';
import { RealtimeProvider } from '@/realtime/provider';
import type { AskStateDTO, PendingPermissionDTO } from '@/api/modules/control';
import { useConversationStore } from '@/stores';

const { toastWarningMock } = vi.hoisted(() => ({
  toastWarningMock: vi.fn(),
}));

let bridgeListener: ((message: Record<string, unknown>) => void) | null = null;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    warning: toastWarningMock,
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
    message: vi.fn(),
  },
}));

vi.mock('@/api/modules/control', async () => {
  const actual = await vi.importActual<
    typeof import('@/api/modules/control')
  >('@/api/modules/control');
  return {
    ...actual,
    getAskState: vi.fn().mockResolvedValue(null),
    respondAsk: vi.fn().mockResolvedValue(undefined),
    respondPermission: vi.fn().mockResolvedValue(undefined),
    listPendingPermissions: vi.fn().mockResolvedValue([]),
    getTodos: vi.fn().mockResolvedValue([
      {
        id: 't1',
        content: 'First todo',
        status: 'in_progress',
        created_at_ms: 0,
        updated_at_ms: 0,
      },
      {
        id: 't2',
        content: 'Second todo',
        status: 'completed',
        created_at_ms: 0,
        updated_at_ms: 0,
      },
    ]),
    getPlanState: vi.fn().mockResolvedValue({
      active: true,
      plan_text: '1. Do thing\n2. Ship it',
      entered_at_ms: 1,
      exited_at_ms: null,
    }),
  };
});

vi.mock('@/realtime/tauri-bridge', () => ({
  TauriBridgeClient: class {
    subscribe(listener: (message: Record<string, unknown>) => void) {
      bridgeListener = listener;
      return () => {
        if (bridgeListener === listener) {
          bridgeListener = null;
        }
      };
    }

    connect() {}

    disconnect() {
      bridgeListener = null;
    }
  },
}));

afterEach(() => {
  bridgeListener = null;
  vi.useRealTimers();
  vi.clearAllMocks();
});

const baseRequest: PendingPermissionDTO = {
  request_id: 'req-1',
  session_id: 'sid-1',
  user_id: 'u1',
  turn_id: null,
  agent_id: 'a1',
  origin: 'main_loop',
  tool_name: 'git_push',
  arguments: { remote: 'origin', branch: 'main' },
  risk_level: 'high',
  workspace: null,
  preview: null,
  signals: [],
  created_at: 0,
  created_at_ms: 0,
  timeout_seconds: 120,
  expires_at_ms: Date.now() + 120_000,
};

const baseAsk: AskStateDTO = {
  request_id: 'ask-1',
  question: 'Which branch should I use?',
  options: ['main', 'develop'],
  allow_free_text: true,
  status: 'pending',
  answer: null,
  created_at_ms: 10,
  timeout_seconds: 300,
  expires_at_ms: Date.now() + 300_000,
};

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
};

describe('PermissionModal', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders the pending tool and posts allow with the selected scope', async () => {
    const { respondPermission } = await import('@/api/modules/control');
    const onResolved = vi.fn();
    const user = userEvent.setup();
    render(
      <PermissionModal
        request={baseRequest}
        open
        onOpenChange={() => undefined}
        onResolved={onResolved}
      />,
    );
    expect(screen.getByTestId('permission-modal')).toBeInTheDocument();
    expect(screen.getByText('git_push')).toBeInTheDocument();
    await user.click(screen.getByTestId('allow-scope-trigger'));
    await user.click(await screen.findByTestId('allow-scope-session'));
    await user.click(screen.getByTestId('allow-btn'));
    await waitFor(() => {
      expect(respondPermission).toHaveBeenCalledWith('req-1', {
        outcome: 'allow',
        scope: 'session',
      });
    });
    await waitFor(() => {
      expect(onResolved).toHaveBeenCalledWith('req-1', 'allow');
    });
  });

  it('posts deny when user rejects', async () => {
    const { respondPermission } = await import('@/api/modules/control');
    const user = userEvent.setup();
    render(
      <PermissionModal
        request={baseRequest}
        open
        onOpenChange={() => undefined}
      />,
    );
    await user.click(screen.getByTestId('deny-scope-trigger'));
    await user.click(await screen.findByTestId('deny-scope-session'));
    await user.click(screen.getByTestId('deny-btn'));
    await waitFor(() => {
      expect(respondPermission).toHaveBeenCalledWith('req-1', {
        outcome: 'deny',
        scope: 'session',
      });
    });
  });

  it('requires a pattern before submitting a pattern rule', async () => {
    const { respondPermission } = await import('@/api/modules/control');
    const user = userEvent.setup();
    render(
      <PermissionModal
        request={baseRequest}
        open
        onOpenChange={() => undefined}
      />,
    );
    await user.click(screen.getByTestId('allow-scope-trigger'));
    await user.click(await screen.findByTestId('allow-scope-persistent_pattern'));
    await user.click(screen.getByTestId('allow-btn'));

    await waitFor(() => {
      expect(screen.getByText('permission.pattern_required')).toBeInTheDocument();
    });
    expect(respondPermission).not.toHaveBeenCalled();
  });
});

describe('PermissionModalHost', () => {
  beforeEach(() => {
    useConversationStore.getState().reset();
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'sid-1',
        title: 'Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'sid-1');
  });

  it('projects pending permissions into chat status messages', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.listPendingPermissions).mockResolvedValue([baseRequest]);

    render(<PermissionModalHost sessionId="sid-1" intervalMs={0} />);

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => message.messageKind === 'permission_request')).toBe(true);
    });
  });

  it('auto closes and shows a timeout toast when the active request disappears', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.listPendingPermissions)
      .mockResolvedValueOnce([baseRequest])
      .mockResolvedValueOnce([]);

    render(
      <RealtimeProvider>
        <PermissionModalHost sessionId="sid-1" intervalMs={0} />
      </RealtimeProvider>,
    );

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => message.messageKind === 'permission_request')).toBe(true);
    });

    expect(screen.queryByTestId('permission-modal')).not.toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new CustomEvent('magi-open-permission-request', {
        detail: { requestId: 'req-1' },
      }));
    });

    await waitFor(() => {
      expect(screen.getByTestId('permission-modal')).toBeInTheDocument();
    });

    act(() => {
      bridgeListener?.({
        event: 'control.permission.requested',
        data: { session_id: 'sid-1', request_id: 'req-1' },
      });
    });

    await waitFor(() => {
      expect(screen.queryByTestId('permission-modal')).not.toBeInTheDocument();
    });

    expect(toastWarningMock).toHaveBeenCalledWith('permission.toast_timed_out');
  });

  it('does not project a late permission response from the previous session', async () => {
    const controlApi = await import('@/api/modules/control');
    const firstSession = createDeferred<PendingPermissionDTO[]>();
    const secondSession = createDeferred<PendingPermissionDTO[]>();
    vi.mocked(controlApi.listPendingPermissions).mockImplementation(
      (requestedSessionId) => (
        requestedSessionId === 'sid-1'
          ? firstSession.promise
          : secondSession.promise
      ),
    );
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'sid-1',
        title: 'First chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
      {
        session_id: 'sid-2',
        title: 'Second chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'sid-1');

    const view = render(
      <PermissionModalHost sessionId="sid-1" intervalMs={0} />,
    );
    await waitFor(() => {
      expect(controlApi.listPendingPermissions).toHaveBeenCalledWith('sid-1');
    });

    view.rerender(
      <PermissionModalHost sessionId="sid-2" intervalMs={0} />,
    );
    await waitFor(() => {
      expect(controlApi.listPendingPermissions).toHaveBeenCalledWith('sid-2');
    });

    await act(async () => {
      secondSession.resolve([]);
      await secondSession.promise;
      firstSession.resolve([{ ...baseRequest, session_id: 'sid-1' }]);
      await firstSession.promise;
    });

    expect(
      useConversationStore.getState().messagesBySession['sid-2']
        ?.some((message) => message.messageKind === 'permission_request'),
    ).not.toBe(true);
  });

  it('does not restore a permission after its chat history is cleared', async () => {
    const controlApi = await import('@/api/modules/control');
    const response = createDeferred<PendingPermissionDTO[]>();
    vi.mocked(controlApi.listPendingPermissions).mockReturnValue(
      response.promise,
    );

    render(<PermissionModalHost sessionId="sid-1" intervalMs={0} />);
    await waitFor(() => {
      expect(controlApi.listPendingPermissions).toHaveBeenCalledWith('sid-1');
    });

    act(() => {
      dispatchAppEvent.chatHistoryCleared('sid-1');
    });
    await act(async () => {
      response.resolve([{ ...baseRequest, session_id: 'sid-1' }]);
      await response.promise;
    });

    expect(
      useConversationStore.getState().messagesBySession['sid-1']
        ?.some((message) => message.messageKind === 'permission_request'),
    ).not.toBe(true);
  });
});

describe('AskDialog', () => {
  beforeEach(() => {
    useConversationStore.getState().reset();
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'sid-1',
        title: 'Chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'sid-1');
  });

  it('projects pending asks into assistant chat messages', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.getAskState).mockResolvedValue(baseAsk);

    render(<AskDialog sessionId="sid-1" intervalMs={0} />);

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => message.messageKind === 'ask_request' && message.kind === 'assistant')).toBe(true);
    });
    expect(screen.queryByTestId('ask-dialog')).not.toBeInTheDocument();
  });

  it('does not continuously poll ask state when polling is disabled', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.useFakeTimers();
    vi.mocked(controlApi.getAskState).mockResolvedValue(null);

    render(<AskDialog sessionId="sid-1" intervalMs={0} />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(vi.mocked(controlApi.getAskState)).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    expect(vi.mocked(controlApi.getAskState)).toHaveBeenCalledTimes(1);
  });

  it('recovers a pending ask through polling when the realtime wake-up is missed', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.useFakeTimers();
    vi.mocked(controlApi.getAskState)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(baseAsk);

    try {
      render(<AskDialog sessionId="sid-1" intervalMs={50} />);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60);
      });

      expect(vi.mocked(controlApi.getAskState)).toHaveBeenCalledTimes(2);
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => message.messageKind === 'ask_request')).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('wakes a pending ask from ask_user_question tool-call chunks when the control wake-up is missed', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.getAskState)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(baseAsk);

    render(
      <RealtimeProvider>
        <AskDialog sessionId="sid-1" intervalMs={0} />
      </RealtimeProvider>,
    );

    await waitFor(() => {
      expect(vi.mocked(controlApi.getAskState)).toHaveBeenCalledTimes(1);
    });

    act(() => {
      bridgeListener?.({
        event: 'agent_response_chunk',
        data: {
          session_id: 'sid-1',
          turn_id: 'turn-ask-chunk',
          event: {
            kind: 'tool_call_end',
            tool_name: 'ask_user_question',
            tool_arguments: {
              question: baseAsk.question,
              options: baseAsk.options,
              allow_free_text: baseAsk.allow_free_text,
            },
          },
        },
      });
    });

    await waitFor(() => {
      expect(vi.mocked(controlApi.getAskState)).toHaveBeenCalledTimes(2);
    });

    const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
    expect(messages.some((message) => message.messageKind === 'ask_request')).toBe(true);
  });

  it('preserves existing ask transcript messages when no ask is currently pending', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.getAskState).mockResolvedValue(null);

    useConversationStore.getState().upsertMessage('sid-1', {
      id: 'ask:historic-ask',
      messageId: 'ask:historic-ask',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Historic question',
      timestamp: Date.now() - 5_000,
      payload: {
        ask_request_id: 'historic-ask',
        status: 'pending',
        question: 'Historic question',
      },
    });

    render(<AskDialog sessionId="sid-1" intervalMs={0} />);

    await waitFor(() => {
      expect(vi.mocked(controlApi.getAskState)).toHaveBeenCalled();
    });

    const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
    expect(messages.some((message) => message.messageId === 'ask:historic-ask')).toBe(true);
  });

  it('does not delete older ask transcript messages when a new ask becomes pending', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.getAskState).mockResolvedValue(baseAsk);

    useConversationStore.getState().upsertMessage('sid-1', {
      id: 'ask:historic-answered',
      messageId: 'ask:historic-answered',
      role: 'assistant',
      kind: 'assistant',
      messageKind: 'ask_request',
      content: 'Earlier question',
      timestamp: Date.now() - 10_000,
      payload: {
        ask_request_id: 'historic-answered',
        status: 'answered',
        question: 'Earlier question',
        answer: 'Earlier answer',
      },
    });

    render(<AskDialog sessionId="sid-1" intervalMs={0} />);

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => message.messageId === 'ask:ask-1')).toBe(true);
    });

    const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
    expect(messages.some((message) => message.messageId === 'ask:historic-answered')).toBe(true);
  });

  it('does not project a late ask response from the previous session', async () => {
    const controlApi = await import('@/api/modules/control');
    const firstSession = createDeferred<AskStateDTO | null>();
    const secondSession = createDeferred<AskStateDTO | null>();
    vi.mocked(controlApi.getAskState).mockImplementation(
      (requestedSessionId) => (
        requestedSessionId === 'sid-1'
          ? firstSession.promise
          : secondSession.promise
      ),
    );
    useConversationStore.getState().hydrateSessions([
      {
        session_id: 'sid-1',
        title: 'First chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
      {
        session_id: 'sid-2',
        title: 'Second chat',
        last_message_preview: '',
        last_user_message_preview: '',
        title_overridden: false,
        last_timestamp: 0,
        message_count: 0,
        workspace_path: null,
      },
    ], 'sid-1');

    const view = render(<AskDialog sessionId="sid-1" intervalMs={0} />);
    await waitFor(() => {
      expect(controlApi.getAskState).toHaveBeenCalledWith('sid-1');
    });

    view.rerender(<AskDialog sessionId="sid-2" intervalMs={0} />);
    await waitFor(() => {
      expect(controlApi.getAskState).toHaveBeenCalledWith('sid-2');
    });

    await act(async () => {
      secondSession.resolve(null);
      await secondSession.promise;
      firstSession.resolve(baseAsk);
      await firstSession.promise;
    });

    expect(
      useConversationStore.getState().messagesBySession['sid-2']
        ?.some((message) => message.messageKind === 'ask_request'),
    ).not.toBe(true);
  });

  it('does not restore an ask after its chat history is cleared', async () => {
    const controlApi = await import('@/api/modules/control');
    const response = createDeferred<AskStateDTO | null>();
    vi.mocked(controlApi.getAskState).mockReturnValue(response.promise);

    render(<AskDialog sessionId="sid-1" intervalMs={0} />);
    await waitFor(() => {
      expect(controlApi.getAskState).toHaveBeenCalledWith('sid-1');
    });

    act(() => {
      dispatchAppEvent.chatHistoryCleared('sid-1');
    });
    await act(async () => {
      response.resolve(baseAsk);
      await response.promise;
    });

    expect(
      useConversationStore.getState().messagesBySession['sid-1']
        ?.some((message) => message.messageKind === 'ask_request'),
    ).not.toBe(true);
  });
});
