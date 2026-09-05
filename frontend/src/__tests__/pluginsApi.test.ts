import { beforeEach, describe, expect, it, vi } from 'vitest';
import examples from '../../../contracts/api/frontend-plugins-examples.json';

const transport = vi.hoisted(() => ({
  delete: vi.fn<(...args: unknown[]) => Promise<unknown>>(),
  get: vi.fn<(...args: unknown[]) => Promise<unknown>>(),
  post: vi.fn<(...args: unknown[]) => Promise<unknown>>(),
  put: vi.fn<(...args: unknown[]) => Promise<unknown>>(),
}));
vi.mock('@/api/client', () => ({ api: transport, unwrapGatewayPayload: (value: unknown) => value }));

import { pluginsApi } from '@/api/modules/plugins';
import { ApiContractError } from '@/api/config-contract';
import { parsePluginPermissionItems, parsePluginResourceGroups } from '@/api/plugin-contract';

const fingerprint = 'f'.repeat(64);
const resource = {
  plugin_id: 'fixture-source', resource_name: 'calendar_lists', resource_type: 'collection',
  data: { groups: [{ group_id: 'icloud', label: 'iCloud', items: [{ item_id: 'personal', label: '个人' }] }] },
};

describe('plugin transport contracts', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.values(transport).forEach(mock => mock.mockReset());
  });

  it('reads the direct resource response without unwrapping its business data', async () => {
    transport.get.mockResolvedValue(resource);
    expect(await pluginsApi.getSettingsResource('fixture-source', 'calendar_lists')).toEqual(resource);
    expect(parsePluginResourceGroups(resource.data.groups)[0].items[0].label).toBe('个人');
  });

  it('rejects an obsolete success envelope', async () => {
    transport.get.mockResolvedValue({ success: true, message: 'OK', data: resource });
    await expect(pluginsApi.getSettingsResource('fixture-source', 'calendar_lists')).rejects.toBeInstanceOf(ApiContractError);
  });

  it('reads actual production package serialization', async () => {
    transport.get.mockResolvedValue(examples.list);
    expect(await pluginsApi.list()).toEqual(examples.list);
    transport.get.mockResolvedValue(examples.package);
    expect(await pluginsApi.getSettings('fixture-source')).toEqual(examples.package);
  });

  it('validates a settings save result before returning it', async () => {
    transport.put.mockResolvedValueOnce(examples.package).mockResolvedValueOnce({ success: false, message: 'Rejected' });
    await expect(pluginsApi.updateSettings('fixture-source', { enabled: true })).resolves.toEqual(examples.package);
    await expect(pluginsApi.updateSettings('fixture-source', { enabled: true })).rejects.toBeInstanceOf(ApiContractError);
  });

  it.each([
    { ...examples.package, healthy: 'yes' },
    { ...examples.package, contributions: [{ ...examples.package.contributions[0], fields: [{ key: 'test' }] }] },
    { ...examples.package, enabled: undefined },
  ])('rejects invalid package fields', async value => {
    transport.post.mockResolvedValue(value);
    await expect(pluginsApi.enable('fixture-source')).rejects.toBeInstanceOf(ApiContractError);
  });

  it('starts, polls, and cancels action sessions using the serialized action contract', async () => {
    transport.post.mockResolvedValue(examples.action);
    await pluginsApi.startSettingsAction('fixture-source', 'connect', { state_dir: '/fixture' });
    await pluginsApi.pollSettingsAction('fixture-source', 'connect', 'fixture-action', {});
    await pluginsApi.cancelSettingsAction('fixture-source', 'connect', 'fixture-action');
    expect(transport.post.mock.calls).toEqual([
      ['/plugins/fixture-source/settings/actions/connect/start', { field_values: { state_dir: '/fixture' } }],
      ['/plugins/fixture-source/settings/actions/connect/sessions/fixture-action/poll', { field_values: {} }],
      ['/plugins/fixture-source/settings/actions/connect/sessions/fixture-action/cancel', {}],
    ]);
  });

  it('rejects an unknown action state instead of treating it as a terminal success', async () => {
    transport.post.mockResolvedValue({ ...examples.action, status: 'almost-done' });
    await expect(pluginsApi.startSettingsAction('fixture-source', 'connect', {})).rejects.toBeInstanceOf(ApiContractError);
  });

  it('starts and polls install jobs with progress callbacks', async () => {
    const progress: string[] = [];
    transport.post.mockResolvedValue({ ...examples.job, status: 'running', result: null });
    transport.get.mockResolvedValue(examples.job);
    const result = await pluginsApi.installFromRegistryWithProgress('fixture-source', fingerprint, snapshot => { progress.push(snapshot.status); });
    expect(progress).toEqual(['running', 'completed']);
    expect(result).toEqual(examples.package);
    expect(transport.post).toHaveBeenCalledWith('/plugins/install/registry/jobs', { plugin_id: 'fixture-source', expected_fingerprint: fingerprint });
    expect(transport.get).toHaveBeenCalledWith('/plugins/install/jobs/fixture-job');
  });

  it('rejects a completed install that has no package result', async () => {
    transport.post.mockResolvedValue({ ...examples.job, result: null });
    await expect(pluginsApi.startInstallFromRegistry('fixture-source', fingerprint)).rejects.toBeInstanceOf(ApiContractError);
  });

  it('preserves the registry-change code from a failed job', async () => {
    transport.post.mockResolvedValue({ ...examples.job, status: 'failed', result: null, error: 'Registry changed', error_code: 'PLUGIN_REGISTRY_CHANGED' });
    await expect(pluginsApi.installFromRegistryWithProgress('fixture-source', fingerprint)).rejects.toMatchObject({ code: 'PLUGIN_REGISTRY_CHANGED', message: 'Registry changed' });
  });

  it('reports the polling deadline with a stable code', async () => {
    vi.spyOn(Date, 'now').mockReturnValueOnce(0).mockReturnValueOnce(10 * 60 * 1000 + 1);
    transport.post.mockResolvedValue({ ...examples.job, status: 'running', result: null });
    await expect(pluginsApi.installFromRegistryWithProgress('fixture-source', fingerprint)).rejects.toMatchObject({ code: 'PLUGIN_INSTALL_TIMEOUT' });
  });

  it('uploads once and submits the confirmed archive digest', async () => {
    const candidate = { candidate_id: 'candidate-1', archive_sha256: 'a'.repeat(64), package_sha256: 'b'.repeat(64), expires_at_ms: 123, manifest: examples.package.manifest };
    transport.post.mockResolvedValueOnce(candidate).mockResolvedValueOnce({ ...examples.job, status: 'queued', result: null });
    const created = await pluginsApi.createInstallCandidate(new File(['archive'], 'demo.zip', { type: 'application/zip' }));
    await pluginsApi.startInstallCandidate(created.candidate_id, created.archive_sha256);
    expect(transport.post).toHaveBeenNthCalledWith(1, '/plugins/install/candidates', expect.any(FormData), { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 });
    expect(transport.post).toHaveBeenNthCalledWith(2, '/plugins/install/candidates/candidate-1/jobs', { expected_sha256: candidate.archive_sha256 });
  });

  it('discards an unused candidate', async () => {
    transport.delete.mockResolvedValue(undefined);
    await pluginsApi.discardInstallCandidate('candidate-1');
    expect(transport.delete).toHaveBeenCalledWith('/plugins/install/candidates/candidate-1');
  });

  it('sends approved fingerprints on direct install, update, and update-job requests', async () => {
    transport.post.mockResolvedValueOnce(examples.package).mockResolvedValueOnce(examples.package).mockResolvedValueOnce(examples.job);
    await pluginsApi.installFromRegistry('fixture-source', fingerprint);
    await pluginsApi.updatePlugin('fixture-source', fingerprint);
    await pluginsApi.startUpdatePlugin('fixture-source', fingerprint);
    expect(transport.post.mock.calls).toEqual([
      ['/plugins/install/registry', { plugin_id: 'fixture-source', expected_fingerprint: fingerprint }],
      ['/plugins/fixture-source/update', { expected_fingerprint: fingerprint }],
      ['/plugins/fixture-source/update/jobs', { expected_fingerprint: fingerprint }],
    ]);
  });

  it('fetches a valid registry and only bypasses its cache when requested', async () => {
    transport.get.mockResolvedValue({ plugins: [], registry_version: '4', install_fingerprint: fingerprint });
    await pluginsApi.getRegistry();
    await pluginsApi.getRegistry({ force: true });
    expect(transport.get.mock.calls).toEqual([['/plugins/registry'], ['/plugins/registry', { refresh: true }]]);
    transport.get.mockResolvedValue({ plugins: [], registry_version: '4' });
    await expect(pluginsApi.getRegistry()).rejects.toBeInstanceOf(ApiContractError);
  });

  it('rejects malformed dynamic resources instead of displaying empty lists', () => {
    expect(() => parsePluginResourceGroups(undefined)).toThrow(ApiContractError);
    expect(() => parsePluginResourceGroups([{ group_id: 'test', label: 'Test', items: [{ item_id: 7 }] }])).toThrow(ApiContractError);
    expect(() => parsePluginPermissionItems([{ id: 'calendar', label: 'Calendar', status: true }])).toThrow(ApiContractError);
    expect(parsePluginPermissionItems([{ id: 'calendar', label: 'Calendar', status: 'denied', settings_url: 'x-apple.systempreferences:fixture' }])[0].settings_url).toBe('x-apple.systempreferences:fixture');
  });
});
