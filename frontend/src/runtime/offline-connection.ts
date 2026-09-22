import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';
import { assertRuntimeGeneration, getRuntimeConfig, getRuntimeGeneration } from './config';
import { bindOfflineCenterStorageScope } from './center-storage';
import type { ConnectionProfile } from './connections';

const descriptorSchema = z.object({
  version: z.literal(1),
  profileId: z.string().min(1),
  mode: z.enum(['local', 'remote']),
  serverId: z.string().uuid(),
  dataEpoch: z.string().min(1).max(128),
  contentEpoch: z.string().min(1).max(128),
  verifiedAtMs: z.number().int().positive(),
});
export type OfflineConnection = z.infer<typeof descriptorSchema>;
const blockedKey = (serverId: string) => `magi.offline.blocked.${encodeURIComponent(serverId)}`;

/** Persist before starting maintenance, including before a request can lose its response. */
export function blockOfflineContent(serverId: string): void {
  const key = blockedKey(serverId);
  window.localStorage.setItem(key, 'true');
  if (window.localStorage.getItem(key) !== 'true') throw new Error('Could not suspend saved content access');
}

export async function invalidateOfflineConnection(): Promise<void> {
  const runtime = getRuntimeConfig();
  const owner = getRuntimeGeneration();
  if (!runtime.serverId) return;
  let markerFailure: unknown;
  try { blockOfflineContent(runtime.serverId); }
  catch (error) { markerFailure = error; }
  if (runtime.connectionGeneration !== undefined) {
    await invoke('invalidate_offline_connection', { connectionGeneration: runtime.connectionGeneration });
    assertRuntimeGeneration(owner);
  } else if (markerFailure) {
    throw markerFailure;
  }
}

/** Only a completed online bootstrap may make a snapshot eligible again. */
export async function confirmOfflineConnection(): Promise<void> {
  const runtime = getRuntimeConfig();
  const owner = getRuntimeGeneration();
  if (!runtime.serverId || runtime.connectionGeneration === undefined) throw new Error('Center identity is missing');
  const raw = await invoke<unknown>('confirm_offline_connection', { connectionGeneration: runtime.connectionGeneration });
  assertRuntimeGeneration(owner);
  const descriptor = descriptorSchema.parse(raw);
  if (descriptor.serverId !== runtime.serverId || descriptor.profileId !== runtime.profileId
    || descriptor.contentEpoch !== runtime.contentEpoch || descriptor.dataEpoch !== runtime.dataEpoch) {
    await invalidateOfflineConnection();
    throw new Error('Center data changed during connection; reconnect to refresh it');
  }
  try { window.localStorage.removeItem(blockedKey(descriptor.serverId)); }
  catch { /* A retained marker disables offline access without blocking the live app. */ }
}

/** The native owner permits this only after a classified network-unavailable failure. */
export async function readOfflineConnection(profile: ConnectionProfile): Promise<OfflineConnection | null> {
  const owner = getRuntimeGeneration();
  const raw = await invoke<unknown>('read_offline_connection');
  assertRuntimeGeneration(owner);
  if (raw === null) return null;
  const descriptor = descriptorSchema.parse(raw);
  if (descriptor.profileId !== profile.id || descriptor.mode !== profile.mode
    || (profile.mode === 'remote' && descriptor.serverId !== profile.server_id)
    || descriptor.verifiedAtMs > Date.now() + 60_000
    || window.localStorage.getItem(blockedKey(descriptor.serverId))) return null;
  return descriptor;
}

export function openOfflineConnection(descriptor: OfflineConnection): void {
  if (window.localStorage.getItem(blockedKey(descriptor.serverId))) throw new Error('Saved content access is suspended');
  bindOfflineCenterStorageScope(descriptor.serverId, descriptor.contentEpoch);
}
