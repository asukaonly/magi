import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
  },
}));

import { api } from '@/api/client';
import { pluginsApi } from '@/api/modules/plugins';

describe('pluginsApi.getSettingsResource', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it('keeps plain settings resource payloads intact when they contain business data fields', async () => {
    vi.mocked(api.get).mockResolvedValue({
      plugin_id: 'calendar',
      resource_name: 'calendar_lists',
      resource_type: 'collection',
      data: {
        groups: [
          {
            group_id: 'icloud',
            label: 'iCloud',
            items: [{ item_id: 'personal', label: '个人' }],
          },
        ],
      },
    } as any);

    const payload = await pluginsApi.getSettingsResource('calendar', 'calendar_lists');

    expect(payload).toEqual({
      plugin_id: 'calendar',
      resource_name: 'calendar_lists',
      resource_type: 'collection',
      data: {
        groups: [
          {
            group_id: 'icloud',
            label: 'iCloud',
            items: [{ item_id: 'personal', label: '个人' }],
          },
        ],
      },
    });
  });

  it('still unwraps legacy success envelopes', async () => {
    vi.mocked(api.get).mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        plugin_id: 'calendar',
        resource_name: 'calendar_lists',
        resource_type: 'collection',
        data: {
          groups: [],
        },
      },
    } as any);

    const payload = await pluginsApi.getSettingsResource('calendar', 'calendar_lists');

    expect(payload).toEqual({
      plugin_id: 'calendar',
      resource_name: 'calendar_lists',
      resource_type: 'collection',
      data: {
        groups: [],
      },
    });
  });
});
