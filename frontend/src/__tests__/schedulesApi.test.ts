import { describe, expect, it, vi, beforeEach } from 'vitest';

const { apiGet, apiPost, apiPatch, apiDelete } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  api: {
    get: apiGet,
    post: apiPost,
    patch: apiPatch,
    delete: apiDelete,
  },
  unwrapGatewayPayload: <T,>(value: T) => value,
}));

import { schedulesApi } from '@/api/modules/schedules';

describe('schedulesApi', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    apiPatch.mockReset();
    apiDelete.mockReset();
  });

  it('listActivity passes since/until/limit/targetTypes/statuses query params', async () => {
    apiGet.mockResolvedValue({ activities: [] });
    await schedulesApi.listActivity({
      sinceSeconds: 1000,
      untilSeconds: 2000,
      limit: 50,
      targetTypes: ['user_agent_task', 'memory_l3_summary'],
      statuses: ['succeeded', 'failed'],
    });
    const url = apiGet.mock.calls[0][0] as string;
    expect(url).toContain('since=1000');
    expect(url).toContain('until=2000');
    expect(url).toContain('limit=50');
    expect(url).toContain('target_types=user_agent_task');
    expect(url).toContain('target_types=memory_l3_summary');
    expect(url).toContain('statuses=succeeded');
    expect(url).toContain('statuses=failed');
  });

  it('listActivity with no params hits the bare /activity URL', async () => {
    apiGet.mockResolvedValue({ activities: [] });
    await schedulesApi.listActivity();
    expect(apiGet.mock.calls[0][0]).toBe('/schedules/activity');
  });

  it('create posts the correct schedule body', async () => {
    apiPost.mockResolvedValue({ schedule: { schedule_id: 'user-1' } });
    await schedulesApi.create({
      schedule_id: 'user-1',
      display_name: 'Daily summary',
      prompt: 'Summarize my day',
      trigger: { trigger_type: 'interval', config: { seconds: 86400 } },
      enabled: true,
    });
    expect(apiPost).toHaveBeenCalledWith(
      '/schedules',
      expect.objectContaining({
        schedule_id: 'user-1',
        target_type: 'user_agent_task',
        target_key: 'user-1',
        target_payload: expect.objectContaining({ prompt: 'Summarize my day' }),
        metadata: expect.objectContaining({ display_name: 'Daily summary' }),
        enabled: true,
      }),
    );
  });
});
