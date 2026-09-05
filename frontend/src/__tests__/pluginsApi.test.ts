import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    delete: vi.fn(),
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
    vi.mocked(api.delete).mockReset();
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

    const payload = await pluginsApi.startSettingsAction('weixin', 'qr_login', { display_name: 'Work' });

    expect(api.post).toHaveBeenCalledWith('/plugins/connections/weixin/settings/actions/qr_login/start', {
      field_values: { display_name: 'Work' },
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
      '/plugins/connections/weixin/settings/actions/qr_login/sessions/session-1/poll',
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
      '/plugins/connections/weixin/settings/actions/qr_login/sessions/session-1/cancel',
      {}
    );
    expect(payload.status).toBe('cancelled');
  });

  it('starts and polls registry install jobs with progress callbacks', async () => {
    const progressSnapshots: string[] = [];
    vi.mocked(api.post).mockResolvedValue({
      job_id: 'job-1',
      operation: 'install',
      plugin_id: 'calendar',
      filename: null,
      status: 'running',
      stage: 'download',
      progress_pct: 20,
      message: 'Downloading plugin source',
      error: null,
      logs: [],
      result: null,
      created_at_ms: 1,
      updated_at_ms: 1,
      finished_at_ms: null,
    } as any);
    vi.mocked(api.get).mockResolvedValue({
      job_id: 'job-1',
      operation: 'install',
      plugin_id: 'calendar',
      filename: null,
      status: 'completed',
      stage: 'completed',
      progress_pct: 100,
      message: 'Plugin installation completed',
      error: null,
      logs: [],
      result: {
        manifest: {
          plugin_id: 'calendar',
          name: 'Calendar',
          version: '1.0.0',
          description: '',
          author: 'Magi',
          official: true,
          contribution_types: ['sensor'],
          source: 'external',
          plugin_dir: '/tmp/calendar',
          manifest_path: '/tmp/calendar/plugin.toml',
        },
        enabled: true,
        trusted: false,
        loaded: true,
        healthy: true,
        last_error: null,
        contributions: [],
        current_settings: {},
      },
      created_at_ms: 1,
      updated_at_ms: 2,
      finished_at_ms: 2,
    } as any);

    const result = await pluginsApi.installFromRegistryWithProgress(
      'calendar',
      'fingerprint-1',
      (snapshot) => {
        progressSnapshots.push(snapshot.status);
      },
    );

    expect(api.post).toHaveBeenCalledWith('/plugins/install/registry/jobs', {
      plugin_id: 'calendar',
      expected_fingerprint: 'fingerprint-1',
    });
    expect(api.get).toHaveBeenCalledWith('/plugins/install/jobs/job-1');
    expect(progressSnapshots).toEqual(['running', 'completed']);
    expect(result.manifest.plugin_id).toBe('calendar');
  });

  it('preserves a registry-change code reported by a failed install job', async () => {
    vi.mocked(api.post).mockResolvedValue({
      job_id: 'job-stale',
      operation: 'install',
      plugin_id: 'calendar',
      filename: null,
      status: 'failed',
      stage: 'validate',
      progress_pct: 40,
      message: 'Registry changed',
      error: 'Registry changed',
      error_code: 'PLUGIN_REGISTRY_CHANGED',
      logs: [],
      result: null,
      created_at_ms: 1,
      updated_at_ms: 2,
      finished_at_ms: 2,
    } as any);

    await expect(
      pluginsApi.installFromRegistryWithProgress(
        'calendar',
        'fingerprint-old',
      ),
    ).rejects.toMatchObject({
      code: 'PLUGIN_REGISTRY_CHANGED',
      message: 'Registry changed',
    });
  });

  it('reports the local polling deadline with a stable code', async () => {
    const now = vi
      .spyOn(Date, 'now')
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(10 * 60 * 1000 + 1);
    vi.mocked(api.post).mockResolvedValue({
      job_id: 'job-timeout',
      operation: 'install',
      plugin_id: 'calendar',
      filename: null,
      status: 'running',
      stage: 'download',
      progress_pct: 20,
      message: 'Downloading plugin source',
      error: null,
      logs: [],
      result: null,
      created_at_ms: 1,
      updated_at_ms: 1,
      finished_at_ms: null,
    } as any);

    await expect(
      pluginsApi.installFromRegistryWithProgress(
        'calendar',
        'fingerprint-current',
      ),
    ).rejects.toMatchObject({
      code: 'PLUGIN_INSTALL_TIMEOUT',
    });

    now.mockRestore();
  });

  it('uploads once and starts installation with the returned candidate digest', async () => {
    const candidate = {
      candidate_id: 'candidate-1',
      archive_sha256: 'a'.repeat(64),
      package_sha256: 'b'.repeat(64),
      expires_at_ms: 123,
      manifest: {
        plugin_id: 'demo-plugin',
        name: 'Demo Plugin',
        version: '1.0.0',
        description: '',
        author: 'Demo',
        official: false,
        contribution_types: [],
        source: 'external',
        plugin_dir: '',
        manifest_path: '',
        capabilities: [],
      },
    };
    vi.mocked(api.post)
      .mockResolvedValueOnce(candidate as any)
      .mockResolvedValueOnce({
        job_id: 'job-1',
        operation: 'upload',
        plugin_id: 'demo-plugin',
        filename: 'demo.zip',
        status: 'queued',
        stage: 'queued',
        progress_pct: 0,
        message: 'Queued plugin installation',
        logs: [],
        created_at_ms: 1,
        updated_at_ms: 1,
      } as any);
    const file = new File(['archive'], 'demo.zip', { type: 'application/zip' });

    const created = await pluginsApi.createInstallCandidate(file);
    await pluginsApi.startInstallCandidate(created.candidate_id, created.archive_sha256);

    expect(api.post).toHaveBeenNthCalledWith(
      1,
      '/plugins/install/candidates',
      expect.any(FormData),
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      },
    );
    const formData = vi.mocked(api.post).mock.calls[0][1] as FormData;
    expect(formData.get('file')).toBe(file);
    expect(api.post).toHaveBeenNthCalledWith(
      2,
      '/plugins/install/candidates/candidate-1/jobs',
      { expected_sha256: 'a'.repeat(64) },
    );
  });

  it('discards an unused install candidate', async () => {
    vi.mocked(api.delete).mockResolvedValue({} as any);

    await pluginsApi.discardInstallCandidate('candidate-1');

    expect(api.delete).toHaveBeenCalledWith('/plugins/install/candidates/candidate-1');
  });

  it('sends the confirmed registry fingerprint on direct install and update requests', async () => {
    vi.mocked(api.post).mockResolvedValue({} as any);

    await pluginsApi.installFromRegistry('calendar', 'fingerprint-confirmed');
    await pluginsApi.updatePlugin('calendar', 'fingerprint-confirmed');

    expect(api.post).toHaveBeenNthCalledWith(
      1,
      '/plugins/install/registry',
      {
        plugin_id: 'calendar',
        expected_fingerprint: 'fingerprint-confirmed',
      },
    );
    expect(api.post).toHaveBeenNthCalledWith(
      2,
      '/plugins/calendar/update',
      { expected_fingerprint: 'fingerprint-confirmed' },
    );
  });

  it('sends the confirmed registry fingerprint when starting an update job', async () => {
    vi.mocked(api.post).mockResolvedValue({} as any);

    await pluginsApi.startUpdatePlugin('calendar', 'fingerprint-confirmed');

    expect(api.post).toHaveBeenCalledWith(
      '/plugins/calendar/update/jobs',
      { expected_fingerprint: 'fingerprint-confirmed' },
    );
  });

  it('fetches the registry without cache-bypass params by default', async () => {
    vi.mocked(api.get).mockResolvedValue({ plugins: [], registry_version: '4' } as any);

    await pluginsApi.getRegistry();

    expect(api.get).toHaveBeenCalledWith('/plugins/registry');
  });

  it('passes refresh=true to bypass the registry cache when forced', async () => {
    vi.mocked(api.get).mockResolvedValue({ plugins: [], registry_version: '4' } as any);

    await pluginsApi.getRegistry({ force: true });

    expect(api.get).toHaveBeenCalledWith('/plugins/registry', { refresh: true });
  });
});
