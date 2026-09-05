import type { Event, EventCallback, UnlistenFn } from '@tauri-apps/api/event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TauriBridgeClient } from '@/realtime/tauri-bridge';

const { listen } = vi.hoisted(() => ({
  listen: vi.fn<(name: string, callback: EventCallback<unknown>) => Promise<UnlistenFn>>(),
}));
vi.mock('@tauri-apps/api/event', () => ({ listen }));
const notification: Event<unknown> = {
  event: 'agent_response', id: 1,
  payload: { channel: 'agent_response', user_id: 'u', session_id: 's', turn_id: null, data: { content: 'Hello' } },
};

beforeEach(() => listen.mockReset());

describe('desktop bridge subscription ownership', () => {
  it('deduplicates pending connections and releases all subscriptions on disconnect', async () => {
    const release = vi.fn();
    listen.mockResolvedValue(release);
    const client = new TauriBridgeClient();
    const connecting = client.connect();
    expect(client.connect()).toBe(connecting);
    await connecting;
    expect(listen).toHaveBeenCalledTimes(18);
    await client.connect();
    expect(listen).toHaveBeenCalledTimes(18);
    client.disconnect();
    expect(release).toHaveBeenCalledTimes(18);
  });

  it('releases a subscription resolving after disconnect without connecting again', async () => {
    let finish: ((release: UnlistenFn) => void) | undefined;
    listen.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const client = new TauriBridgeClient();
    const subscriber = vi.fn();
    const status = vi.fn();
    client.subscribe(subscriber);
    client.subscribeStatus(status);
    const connecting = client.connect();
    client.disconnect();
    const release = vi.fn();
    finish?.(release);
    await connecting;
    listen.mock.calls[0][1](notification);
    expect(release).toHaveBeenCalledOnce();
    expect(listen).toHaveBeenCalledOnce();
    expect(subscriber).not.toHaveBeenCalled();
    expect(status.mock.lastCall?.[0].connected).toBe(false);
  });

  it('cleans partial failure and allows a fresh connection', async () => {
    const released = vi.fn();
    listen.mockResolvedValueOnce(released).mockRejectedValueOnce(new Error('Host unavailable'));
    const client = new TauriBridgeClient();
    const status = vi.fn();
    client.subscribeStatus(status);
    await expect(client.connect()).rejects.toThrow('Host unavailable');
    expect(released).toHaveBeenCalledOnce();
    expect(status.mock.lastCall?.[0]).toMatchObject({ connected: false, lastError: 'Host unavailable' });
    listen.mockImplementation(async () => vi.fn<UnlistenFn>());
    await client.connect();
    expect(status.mock.lastCall?.[0]).toMatchObject({ connected: true, lastError: null });
    client.disconnect();
  });

  it('does not let an old pending registration contaminate a new connection', async () => {
    let finish: ((release: UnlistenFn) => void) | undefined;
    listen.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const client = new TauriBridgeClient();
    const stale = client.connect();
    client.disconnect();
    const currentReleases: Array<ReturnType<typeof vi.fn>> = [];
    listen.mockImplementation(async () => {
      const release = vi.fn();
      currentReleases.push(release);
      return release;
    });
    await client.connect();
    const oldRelease = vi.fn();
    finish?.(oldRelease);
    await stale;
    expect(oldRelease).toHaveBeenCalledOnce();
    expect(currentReleases.every(release => release.mock.calls.length === 0)).toBe(true);
    client.disconnect();
    expect(currentReleases.every(release => release.mock.calls.length === 1)).toBe(true);
  });

  it('rejects malformed host payloads and isolates subscriber exceptions', async () => {
    listen.mockImplementation(async () => vi.fn<UnlistenFn>());
    const client = new TauriBridgeClient();
    const badSubscriber = vi.fn(() => { throw new Error('View failed'); });
    const goodSubscriber = vi.fn();
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    client.subscribe(badSubscriber);
    client.subscribe(goodSubscriber);
    await client.connect();
    const callback = listen.mock.calls[0][1];
    callback({ ...notification, payload: { data: [] } });
    expect(goodSubscriber).not.toHaveBeenCalled();
    callback(notification);
    expect(goodSubscriber).toHaveBeenCalledOnce();
    expect(log).toHaveBeenCalledOnce();
    client.disconnect();
    log.mockRestore();
  });
});
