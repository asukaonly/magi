/**
 * Smoke tests for the control-plane components.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PermissionModal } from '@/components/control/PermissionModal';
import { TodoPanel } from '@/components/control/TodoPanel';
import { PlanCard } from '@/components/control/PlanCard';
import type { PendingPermissionDTO } from '@/api/modules/control';

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
    respondPermission: vi.fn().mockResolvedValue(undefined),
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

describe('TodoPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders todos fetched from the API', async () => {
    render(<TodoPanel sessionId="sid-1" intervalMs={0} />);
    await waitFor(() => {
      expect(screen.getByTestId('todo-t1')).toBeInTheDocument();
      expect(screen.getByTestId('todo-t2')).toBeInTheDocument();
    });
    expect(screen.getByText('First todo')).toBeInTheDocument();
  });

  it('renders the empty state when no session id is provided', () => {
    render(<TodoPanel sessionId={null} intervalMs={0} />);
    expect(screen.getByText('todo.empty')).toBeInTheDocument();
  });
});

describe('PlanCard', () => {
  it('renders plan text when the session is in plan mode', async () => {
    render(<PlanCard sessionId="sid-1" intervalMs={0} />);
    await waitFor(() => {
      expect(screen.getByTestId('plan-card')).toBeInTheDocument();
      expect(screen.getByText(/Do thing/)).toBeInTheDocument();
    });
  });
});
