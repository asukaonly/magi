/**
 * Smoke tests for the control-plane components.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PermissionModal } from '@/components/control/PermissionModal';
import { AskDialog } from '@/components/control/AskDialog';
import { PermissionModalHost } from '@/components/control/PermissionModalHost';
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
};

const baseAsk: AskStateDTO = {
  request_id: 'ask-1',
  question: 'Which branch should I use?',
  options: ['main', 'develop'],
  allow_free_text: true,
  status: 'pending',
  answer: null,
  created_at_ms: 10,
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

  it('projects pending asks into chat status messages', async () => {
    const controlApi = await import('@/api/modules/control');
    vi.mocked(controlApi.getAskState).mockResolvedValue(baseAsk);

    render(<AskDialog sessionId="sid-1" intervalMs={0} />);

    await waitFor(() => {
      const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
      expect(messages.some((message) => message.messageKind === 'ask_request')).toBe(true);
    });
    expect(screen.getByTestId('ask-dialog')).toBeInTheDocument();
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
      expect(screen.getByTestId('ask-dialog')).toBeInTheDocument();

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
      expect(screen.getByTestId('ask-dialog')).toBeInTheDocument();
    });

    const messages = useConversationStore.getState().messagesBySession['sid-1'] || [];
    expect(messages.some((message) => message.messageKind === 'ask_request')).toBe(true);
  });
});
