import { beforeEach, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }));
vi.mock('@/api/client', () => ({ api }));
import { pluginsApi } from '@/api/modules/plugins';

beforeEach(() => vi.clearAllMocks());

it('sends explicit connection identity and optimistic revisions on every mutation', async () => {
  api.patch.mockResolvedValue({ connection_id: 'one' });
  api.post.mockResolvedValue({ connection_id: 'one' });
  await pluginsApi.updateConnection('example', 'one', { expected_revision: 2, enabled: true });
  expect(api.patch).toHaveBeenCalledWith('/plugins/example/connections/one', { expected_revision: 2, enabled: true });
  await pluginsApi.clearConnectionContent('example', 'one', 3);
  expect(api.post).toHaveBeenCalledWith('/plugins/example/connections/one/clear', { expected_revision: 3 });
  await pluginsApi.disconnectConnection('example', 'one', 4);
  expect(api.delete).toHaveBeenCalledWith('/plugins/example/connections/one', { params: { expected_revision: 4 } });
});

it('reads the authoritative connection collection', async () => {
  api.get.mockResolvedValue({ connections: [{ connection_id: 'one' }], total: 1 });
  expect(await pluginsApi.listConnections('example')).toEqual([{ connection_id: 'one' }]);
});

it('binds execution authorization to the reviewed package digest', async () => {
  api.post.mockResolvedValue({ trusted: true });
  await pluginsApi.authorizePackage('example', 'a'.repeat(64));
  expect(api.post).toHaveBeenCalledWith('/plugins/example/trust', { expected_package_sha256: 'a'.repeat(64) });
});
