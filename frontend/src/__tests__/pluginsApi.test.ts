import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from '@/api/client';
import { pluginsApi } from '@/api/modules/plugins';

describe('pluginsApi.getSettingsResource', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
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

  it('starts plugin settings action sessions', async () => {
    vi.mocked(api.post).mockResolvedValue({
      plugin_id: 'weixin',
      action_id: 'qr_login',
      session_id: 'session-1',
      status: 'pending',
      message: 'scan',
      data: { qr_code_url: 'data:image/png;base64,abc' },
      settings_updates: {},
    } as any);

    const payload = await pluginsApi.startSettingsAction('weixin', 'qr_login', { state_dir: '/tmp/magi' });

    expect(api.post).toHaveBeenCalledWith('/plugins/weixin/settings/actions/qr_login/start', {
      field_values: { state_dir: '/tmp/magi' },
    });
    expect(payload.status).toBe('pending');
    expect(payload.data.qr_code_url).toContain('data:image/png');
  });

  it('polls plugin settings action sessions', async () => {
    vi.mocked(api.post).mockResolvedValue({
      success: true,
      data: {
        plugin_id: 'weixin',
        action_id: 'qr_login',
        session_id: 'session-1',
        status: 'succeeded',
        message: 'connected',
        data: {},
        settings_updates: { account_id: 'account-1' },
      },
    } as any);

    const payload = await pluginsApi.pollSettingsAction('weixin', 'qr_login', 'session-1', {});

    expect(api.post).toHaveBeenCalledWith(
      '/plugins/weixin/settings/actions/qr_login/sessions/session-1/poll',
      { field_values: {} }
    );
    expect(payload.settings_updates).toEqual({ account_id: 'account-1' });
  });

  it('cancels plugin settings action sessions', async () => {
    vi.mocked(api.post).mockResolvedValue({
      plugin_id: 'weixin',
      action_id: 'qr_login',
      session_id: 'session-1',
      status: 'cancelled',
      message: 'cancelled',
      data: {},
      settings_updates: {},
    } as any);

    const payload = await pluginsApi.cancelSettingsAction('weixin', 'qr_login', 'session-1');

    expect(api.post).toHaveBeenCalledWith(
      '/plugins/weixin/settings/actions/qr_login/sessions/session-1/cancel',
      {}
    );
    expect(payload.status).toBe('cancelled');
  });
});
