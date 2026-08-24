import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from '@/api/client';
import {
  getAskState,
  getControlSettings,
  getPlanState,
  getRunPlan,
  listPendingPermissions,
  respondAsk,
  respondPermission,
} from '@/api/modules/control';

describe('control API routes', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.put).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  it('uses baseURL-relative control paths for polling endpoints', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [], ask: null, active: false, plan_text: null, entered_at_ms: null, exited_at_ms: null } } as any);

    await getControlSettings();
    await listPendingPermissions('session-1');
    await getAskState('session-1');
    await getPlanState('session-1');
    await getRunPlan('session-1');

    expect(api.get).toHaveBeenNthCalledWith(1, '/control/settings');
    expect(api.get).toHaveBeenNthCalledWith(2, '/control/sessions/session-1/permissions');
    expect(api.get).toHaveBeenNthCalledWith(3, '/control/sessions/session-1/ask');
    expect(api.get).toHaveBeenNthCalledWith(4, '/control/sessions/session-1/plan');
    expect(api.get).toHaveBeenNthCalledWith(5, '/control/sessions/session-1/todos');
  });

  it('uses baseURL-relative control paths for response endpoints', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true } as any);

    await respondPermission('perm-1', { outcome: 'allow' });
    await respondAsk('ask-1', 'yes');

    expect(api.post).toHaveBeenNthCalledWith(1, '/control/permission/perm-1/respond', { outcome: 'allow' });
    expect(api.post).toHaveBeenNthCalledWith(2, '/control/ask/ask-1/respond', { answer: 'yes' });
  });

  it('unwraps plain backend bodies for todo and permission polling', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({
        items: [
          {
            request_id: 'perm-1',
            session_id: 'session-1',
            user_id: 'local_user',
            turn_id: 'turn-1',
            agent_id: 'chat',
            origin: 'subagent',
            tool: 'bash',
            tool_args: { command: 'pwd' },
            risk_level: 'medium',
            preview: null,
            created_at_ms: 1,
          },
        ],
      } as any)
      .mockResolvedValueOnce({
        plan: {
          plan_id: 'plan-1',
          run_id: 'run-1',
          session_id: 'session-1',
          version: 2,
          required: true,
          status: 'active',
          created_at_ms: 1,
          updated_at_ms: 20,
          items: [
          {
            id: 'todo-1',
            content: 'Inspect runtime drift',
            status: 'in_progress',
            required: true,
            evidence_refs: [],
            blocked_reason: null,
            created_at_ms: 10,
            updated_at_ms: 20,
          },
          ],
        },
      } as any);

    await expect(listPendingPermissions('session-1')).resolves.toEqual([
      expect.objectContaining({ request_id: 'perm-1', tool: 'bash', tool_name: 'bash' }),
    ]);
    await expect(getRunPlan('session-1')).resolves.toEqual(
      expect.objectContaining({
        plan_id: 'plan-1',
        items: [expect.objectContaining({ id: 'todo-1', content: 'Inspect runtime drift' })],
      }),
    );
  });

  it('normalizes legacy ask state fields into the frontend contract', async () => {
    vi.mocked(api.get).mockResolvedValue({
      ask: {
        request_id: 'ask-1',
        question: 'Proceed?',
        options: ['yes'],
        allow_free_text: true,
        resolution: null,
        asked_at: 2,
        timeout_seconds: 5,
        answer: null,
      },
    } as any);

    await expect(getAskState('session-1')).resolves.toEqual(expect.objectContaining({
      request_id: 'ask-1',
      status: 'pending',
      created_at_ms: 2000,
      timeout_seconds: 5,
      expires_at_ms: 7000,
    }));
  });
});
