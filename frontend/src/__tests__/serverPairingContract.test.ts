import { beforeEach, expect, it, vi } from 'vitest';
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('@/api/client', () => ({ api: { post }, unwrapGatewayPayload: (payload: unknown) => payload }));
import { serverApi } from '@/api/modules/server';
const network = { listen_host: '127.0.0.1', listen_port: 52936, lan_ips: ['192.168.1.9', 'fd00::7'] };
const grant = { pairing_token: '01234567'.repeat(8), expires_at_ms: 1234567, network };
beforeEach(() => post.mockReset());
it('retains the center network snapshot with the pairing grant', async () => {
  post.mockResolvedValue(grant);
  await expect(serverApi.pairingGrant()).resolves.toEqual(grant);
  expect(post).toHaveBeenCalledWith('/server/pairing-grants');
});
it.each([
  undefined, { ...network, listen_port: 0 }, { ...network, listen_port: 65536 },
  { ...network, listen_host: 'not-an-ip' }, { ...network, lan_ips: ['http://192.168.1.9'] },
])('rejects malformed or missing network metadata %j', async (invalid) => {
  post.mockResolvedValue({ ...grant, network: invalid });
  await expect(serverApi.pairingGrant()).rejects.toThrow();
});
it('accepts an explicitly unavailable network snapshot', async () => {
  post.mockResolvedValue({ ...grant, network: null });
  await expect(serverApi.pairingGrant()).resolves.toMatchObject({ network: null });
});
