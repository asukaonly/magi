import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { z } from 'zod';
const transport = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), generation: 1 }));
vi.mock('@/api/client', () => ({ api: transport }));
vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({ serverId: 'center', profileId: 'profile', dataEpoch: 'epoch' }),
  getRuntimeGeneration: () => transport.generation,
}));
import { confirmedPluginPost, PluginRequestRejectedError } from '@/api/confirmed-plugin-request';
const parse = (value: unknown) => z.object({ connection_id: z.string() }).parse(value);
const send = () => confirmedPluginPost('/plugins/photos/connections', { credentials: { token: 'private-secret' } }, parse);
const oid = () => transport.post.mock.calls[0][2].headers['X-Magi-Request-Id'];
const completed = () => ({ operation_id: oid(), state: 'completed', http_status: 201, result: { connection_id: 'one' } });
beforeEach(() => { localStorage.clear(); vi.resetAllMocks(); transport.generation = 1; });
afterEach(() => { vi.useRealTimers(); });

it('queries an admitted request after a lost response without repeating the mutation', async () => {
  transport.post.mockRejectedValue(new Error('response lost'));
  transport.get.mockImplementation(async () => completed());
  expect(await send()).toEqual({ connection_id: 'one' });
  expect(transport.post).toHaveBeenCalledTimes(1);
  expect(transport.get.mock.calls[0][0]).toBe(`/plugins/requests/${oid()}`);
  expect(localStorage.length).toBe(0);
});

it('retains only identity after uncertainty and later confirms the same attempt', async () => {
  transport.post.mockImplementation(async () => ({ ...completed(), state: 'uncertain', http_status: null, result: null }));
  await expect(send()).rejects.toThrow('uncertain');
  expect(localStorage.length).toBe(1);
  const retained = localStorage.getItem(localStorage.key(0)!);
  expect(retained).toBe(oid());
  expect(JSON.stringify(localStorage)).not.toContain('private-secret');
  transport.get.mockImplementation(async () => completed());
  expect(await send()).toEqual({ connection_id: 'one' });
  expect(transport.post).toHaveBeenCalledTimes(1);
});

it('resubmits the retained identity only after an explicit not-admitted response', async () => {
  transport.post.mockRejectedValueOnce(new Error('offline'));
  transport.get.mockRejectedValueOnce({ status: 503 });
  await expect(send()).rejects.toMatchObject({ status: 503 });
  const firstId = oid();
  transport.get.mockRejectedValueOnce({ status: 404 });
  transport.post.mockResolvedValueOnce({ connection_id: 'one' });
  expect(await send()).toEqual({ connection_id: 'one' });
  expect(transport.post.mock.calls[1][2].headers['X-Magi-Request-Id']).toBe(firstId);
});

it('keeps the request identity when the owning response contract rejects a result', async () => {
  transport.post.mockResolvedValue({ unexpected: true });
  await expect(send()).rejects.toThrow();
  expect(localStorage.length).toBe(1);
  transport.get.mockImplementation(async () => completed());
  expect(await send()).toEqual({ connection_id: 'one' });
  expect(transport.post).toHaveBeenCalledTimes(1);
});

it('rejects a late result after switching centers', async () => {
  transport.post.mockImplementation(async () => { transport.generation += 1; return { connection_id: 'one' }; });
  await expect(send()).rejects.toThrow('connection changed');
  expect(localStorage.length).toBe(1);
});

it('releases the identity only after a confirmed rejection', async () => {
  transport.post.mockRejectedValue(new Error('request rejected'));
  transport.get.mockImplementation(async () => ({ ...completed(), http_status: 422, result: { detail: 'Invalid settings' } }));
  await expect(send()).rejects.toBeInstanceOf(PluginRequestRejectedError);
  expect(localStorage.length).toBe(0);
});

it('preserves identity when a completed receipt has no status', async () => {
  transport.post.mockImplementation(async () => ({ ...completed(), http_status: null }));
  await expect(send()).rejects.toThrow();
  expect(localStorage.length).toBe(1);
});
