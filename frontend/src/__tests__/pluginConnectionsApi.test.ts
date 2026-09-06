import { beforeEach, expect, it, vi } from 'vitest';
import examples from '../../../contracts/api/frontend-plugins-examples.json';
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock('@/api/client', () => ({ api }));
import { pluginsApi } from '@/api/modules/plugins';
import { ApiContractError } from '@/api/config-contract';

const connection = { ...examples.connection, plugin_id: 'example', connection_id: 'one' };

beforeEach(() => vi.clearAllMocks());

it('sends explicit connection identity and optimistic revisions on every mutation', async () => {
  api.patch.mockResolvedValue(connection);
  api.post.mockResolvedValue(connection);
  await pluginsApi.updateConnection('example', 'one', { expected_revision: 2, enabled: true });
  expect(api.patch).toHaveBeenCalledWith('/plugins/example/connections/one', { expected_revision: 2, enabled: true });
  await pluginsApi.clearConnectionContent('example', 'one', 3);
  expect(api.post).toHaveBeenCalledWith('/plugins/example/connections/one/clear', { expected_revision: 3 });
  await pluginsApi.disconnectConnection('example', 'one', 4);
  expect(api.delete).toHaveBeenCalledWith('/plugins/example/connections/one', { params: { expected_revision: 4 } });
});

it('reads the authoritative connection collection', async () => {
  api.get.mockResolvedValue({ connections: [connection], total: 1 });
  expect(await pluginsApi.listConnections('example')).toEqual([connection]);
});

it('binds execution authorization to the reviewed package digest', async () => {
  api.post.mockResolvedValue({ ...examples.package, trusted: true });
  await pluginsApi.authorizePackage('example', 'a'.repeat(64));
  expect(api.post).toHaveBeenCalledWith('/plugins/example/trust', { expected_package_sha256: 'a'.repeat(64) });
});

it.each([
  { ...connection, revision: -1 },
  { ...connection, connection_id: 'another-account' },
  { ...connection, plugin_id: 'another-plugin' },
  { success: false, message: 'Rejected' },
])('rejects an invalid or unrelated save acknowledgement', async (response) => {
  api.patch.mockResolvedValue(response);
  await expect(pluginsApi.updateConnection('example', 'one', { expected_revision: 2, enabled: true }))
    .rejects.toBeInstanceOf(ApiContractError);
});

it('counts Unicode code points when validating connection names', async () => {
  api.get.mockResolvedValueOnce({ ...connection, display_name: '🙂'.repeat(256) })
    .mockResolvedValueOnce({ ...connection, display_name: '🙂'.repeat(257) });
  await expect(pluginsApi.getConnection('example', 'one')).resolves.toMatchObject({ connection_id: 'one' });
  await expect(pluginsApi.getConnection('example', 'one')).rejects.toBeInstanceOf(ApiContractError);
});
