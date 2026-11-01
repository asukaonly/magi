import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchService, type ServiceSession } from '@/client/http';

afterEach(() => vi.unstubAllGlobals());

describe('service transport without a desktop host', () => {
  const session = (): ServiceSession => ({
    baseUrl: 'https://center.example/api', signal: new AbortController().signal,
    token: async () => 'old', renew: async () => 'new', assertCurrent: () => undefined,
  });
  const rejected = () => Response.json({ error_code: 'client_auth_required' }, { status: 401 });

  it('renews reads and never automatically replays a mutation', async () => {
    const request = vi.fn().mockResolvedValueOnce(rejected()).mockResolvedValueOnce(Response.json({ ok: true }));
    vi.stubGlobal('fetch', request);
    expect((await fetchService(session(), 'https://center.example/api/messages/sessions')).status).toBe(200);
    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls[1][1].headers.get('X-Magi-Session-Token')).toBe('new');
    request.mockReset().mockResolvedValue(rejected());
    expect((await fetchService(session(), 'https://center.example/api/messages/send', { method: 'POST' })).status).toBe(401);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('does not send credentials across origins or dispatch after a connection change', async () => {
    const request = vi.fn(); vi.stubGlobal('fetch', request);
    await expect(fetchService(session(), 'https://another.example/api')).rejects.toThrow('active center');
    const owner = session();
    owner.token = async () => { owner.assertCurrent = () => { throw new Error('Connection changed'); }; return 'old'; };
    await expect(fetchService(owner, 'https://center.example/api/events')).rejects.toThrow('Connection changed');
    expect(request).not.toHaveBeenCalled();
  });
});
