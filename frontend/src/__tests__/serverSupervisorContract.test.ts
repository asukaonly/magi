import { beforeEach, describe, expect, it, vi } from 'vitest';
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/api/client', () => ({ api: { get }, unwrapGatewayPayload: (payload: unknown) => payload }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => ({ serverId: 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0' }) }));
import { serverApi } from '@/api/modules/server';

const info = () => ({
  server_id: 'cde1b1d1-7f23-4b95-a5d4-04e84d209af0', protocol_version: 2, service_ready: false,
  plugin_execution: 'server',
  supervisor: { phase: 'cooldown', restart_count: 3, last_error: 'Python event loop failed consecutive IPC probes', next_retry_at_ms: 123456 },
  maintenance: { version: 2, kind: null, operation_id: null, phase: 'idle', content_epoch: 'initial', data_epoch: 'initial', result: null, error: null },
});

describe('supervisor diagnostics contract', () => {
  beforeEach(() => get.mockReset());
  it('retains cooldown reason and retry deadline through the public client', async () => {
    get.mockResolvedValue(info());
    await expect(serverApi.info()).resolves.toMatchObject({ supervisor: info().supervisor });
  });
  it.each([
    { phase: 'unknown' }, { restart_count: -1 }, { next_retry_at_ms: 'soon' },
  ])('rejects malformed diagnostics %j', async (invalid) => {
    const payload = info();
    get.mockResolvedValue({ ...payload, supervisor: { ...payload.supervisor, ...invalid } });
    await expect(serverApi.info()).rejects.toThrow();
  });
});
