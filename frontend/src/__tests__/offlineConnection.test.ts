import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { invoke } from '@tauri-apps/api/core';
import { blockOfflineContent, confirmOfflineConnection, invalidateOfflineConnection, openOfflineConnection, readOfflineConnection } from '@/runtime/offline-connection';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import type { RuntimeConfig } from '@/runtime/config';
import type { ConnectionProfile } from '@/runtime/connections';

const state = vi.hoisted(() => ({ runtime: {} as RuntimeConfig, generation: 0 }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => state.runtime, getRuntimeGeneration: () => state.generation,
  assertRuntimeGeneration: (owner: number) => { if (owner !== state.generation) throw new Error('Changed connection'); },
}));
const serverId = '11111111-1111-4111-8111-111111111111';
const profile: ConnectionProfile = { mode: 'remote', id: '22222222-2222-4222-8222-222222222222', server_id: serverId, client_id: '33333333-3333-4333-8333-333333333333', name: 'Office', api_base_url: 'https://magi.example/api' };
const descriptor = { version: 1 as const, profileId: profile.id, mode: 'remote' as const, serverId, contentEpoch: 'content-1', dataEpoch: 'data-1', verifiedAtMs: 1_800_000_000_000 };

beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(Date, 'now').mockReturnValue(descriptor.verifiedAtMs + 1000);
  localStorage.clear(); sessionStorage.clear(); state.generation = 1;
  state.runtime = { isDesktop: true, apiBaseUrl: profile.api_base_url, serverId, profileId: profile.id, connectionGeneration: 7, contentEpoch: descriptor.contentEpoch, dataEpoch: descriptor.dataEpoch };
});
afterEach(() => vi.restoreAllMocks());

describe('trusted offline connection', () => {
  it('requires the native active profile network-failure allowance', async () => {
    vi.mocked(invoke).mockResolvedValue(null);
    expect(await readOfflineConnection(profile)).toBeNull();
    vi.mocked(invoke).mockResolvedValue(descriptor);
    expect(await readOfflineConnection(profile)).toEqual(descriptor);
  });
  it.each([
    { profileId: 'another' }, { mode: 'local' }, { serverId: '44444444-4444-4444-8444-444444444444' },
    { verifiedAtMs: descriptor.verifiedAtMs + 120_000 },
  ])('rejects descriptors outside the selected identity: %j', async (change) => {
    vi.mocked(invoke).mockResolvedValue({ ...descriptor, ...change });
    expect(await readOfflineConnection(profile)).toBeNull();
  });
  it('does not delete any epochs when binding an offline snapshot', () => {
    setCenterStorageScope(serverId, 'newer'); centerLocalStorage().setItem('content', 'keep newer');
    openOfflineConnection(descriptor);
    expect(centerLocalStorage().getItem('content')).toBeNull();
    expect(localStorage.getItem(`magi.center.${serverId}.newer.content`)).toBe('keep newer');
  });
  it.each(['maintenance.pending-clear', 'maintenance.pending-restore', 'maintenance.device-cleanup'])('blocks known pending work: %s', (key) => {
    setCenterStorageScope(serverId, descriptor.contentEpoch); centerLocalStorage().setItem(key, 'pending');
    expect(() => openOfflineConnection(descriptor)).toThrow('maintenance');
  });
  it('retains the local stop marker even if native invalidation fails', async () => {
    vi.mocked(invoke).mockRejectedValueOnce(new Error('native unavailable'));
    await expect(invalidateOfflineConnection()).rejects.toThrow('native unavailable');
    vi.mocked(invoke).mockResolvedValue(descriptor);
    expect(await readOfflineConnection(profile)).toBeNull();
    expect(() => openOfflineConnection(descriptor)).toThrow('suspended');
  });
  it('can revoke the native attestation when browser storage is full', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota exceeded'); });
    vi.mocked(invoke).mockResolvedValue(undefined);
    await expect(invalidateOfflineConnection()).resolves.toBeUndefined();
    expect(invoke).toHaveBeenCalledWith('invalidate_offline_connection', { connectionGeneration: 7 });
    vi.mocked(invoke).mockRejectedValue(new Error('Native revoke failed'));
    await expect(invalidateOfflineConnection()).rejects.toThrow('Native revoke failed');
  });
  it('only removes the stop marker after a matching native confirmation', async () => {
    blockOfflineContent(serverId);
    vi.mocked(invoke).mockResolvedValue(descriptor);
    await confirmOfflineConnection();
    expect(invoke).toHaveBeenCalledWith('confirm_offline_connection', { connectionGeneration: 7 });
    expect(await readOfflineConnection(profile)).toEqual(descriptor);
  });
  it('blocks changed epochs instead of confirming stale browser data', async () => {
    vi.mocked(invoke).mockResolvedValueOnce({ ...descriptor, dataEpoch: 'data-2' }).mockResolvedValue(undefined);
    await expect(confirmOfflineConnection()).rejects.toThrow('Center data changed');
    expect(invoke).toHaveBeenCalledWith('invalidate_offline_connection', { connectionGeneration: 7 });
    expect(() => openOfflineConnection(descriptor)).toThrow('suspended');
  });
  it('discards a confirmation that completes after switching connection', async () => {
    let resolve!: (value: unknown) => void;
    blockOfflineContent(serverId);
    vi.mocked(invoke).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const pending = confirmOfflineConnection();
    state.generation += 1; resolve(descriptor);
    await expect(pending).rejects.toThrow('Changed connection');
    expect(() => openOfflineConnection(descriptor)).toThrow('suspended');
  });
});
