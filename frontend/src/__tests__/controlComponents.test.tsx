/**
 * Smoke tests for the control-plane components.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PermissionModal } from '@/components/control/PermissionModal';
import { AskDialog } from '@/components/control/AskDialog';
import { PermissionModalHost } from '@/components/control/PermissionModalHost';
import type { AskStateDTO, PendingPermissionDTO } from '@/api/modules/control';
import { useConversationStore } from '@/stores';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
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

const baseRequest: PendingPermissionDTO = {
  request_id: 'req-1',
  session_id: 'sid-1',
  user_id: 'u1',
  task_id: null,
  agent_id: 'a1',
  origin: 'main_loop',
  tool: 'git_push',
  tool_args: { remote: 'origin', branch: 'main' },
  risk_level: 'high',
  preview: null,
  created_at_ms: 0,
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
    fireEvent.click(screen.getByTestId('scope-session'));
    fireEvent.click(screen.getByTestId('allow-btn'));
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
    render(
      <PermissionModal
        request={baseRequest}
        open
        onOpenChange={() => undefined}
      />,
    );
    fireEvent.click(screen.getByTestId('deny-btn'));
    await waitFor(() => {
      expect(respondPermission).toHaveBeenCalledWith('req-1', {
        outcome: 'deny',
        scope: 'one_shot',
      });
    });
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
});
