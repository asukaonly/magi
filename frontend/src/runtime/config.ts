import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';

export interface RuntimeConfig {
  isDesktop: boolean;
  apiBaseUrl: string;
  sessionToken?: string;
  apiPid?: number;
  runtimeWorkerPid?: number;
  serverId?: string;
  profileId?: string;
  mode?: 'local' | 'remote';
  dataEpoch?: string;
  expiresAtMs?: number;
}

const startSchema = z.object({
  ok: z.literal(true), baseUrl: z.string().url(), sessionToken: z.string().min(32).max(256),
  serverId: z.string().uuid(), profileId: z.string().min(1), mode: z.enum(['local', 'remote']),
  dataEpoch: z.string().min(1).max(128), expiresAtMs: z.number().int().nullable(),
  apiPid: z.number().int().nullable(), runtimeWorkerPid: z.number().int().nullable(),
});
const pollSchema = z.object({ ready: z.boolean(), phase: z.string() });
const sessionSchema = z.object({
  server_id: z.string().uuid(), client_id: z.string().uuid(),
  access_token: z.string().min(32).max(256), expires_at_ms: z.number().int(),
});
const diagnosticsSchema = z.object({
  logPath: z.string().nullish(), logExcerpt: z.string().nullish(), logReadError: z.string().nullish(),
});
export interface BackendStartupDiagnostics {
  logPath?: string;
  logExcerpt?: string;
  logReadError?: string;
}
export type StartupPhase = 'spawning' | 'waiting_for_worker' | 'connecting' | 'recovering_data_clear' | 'ready' | 'error';
export type StartupProgressCallback = (phase: StartupPhase) => void;

let runtimeConfig: RuntimeConfig = { isDesktop: true, apiBaseUrl: 'http://127.0.0.1:8000/api' };
let initialized = false;
let generation = 0;
let initializing: Promise<RuntimeConfig> | undefined;
let renewing: Promise<string | undefined> | undefined;
const resetListeners = new Set<() => void>();

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

export async function readBackendStartupDiagnostics(): Promise<BackendStartupDiagnostics | null> {
  if (!isTauriRuntime()) return null;
  try {
    const result = diagnosticsSchema.parse(await invoke<unknown>('read_backend_startup_diagnostics'));
    return { logPath: result.logPath ?? undefined, logExcerpt: result.logExcerpt ?? undefined, logReadError: result.logReadError ?? undefined };
  } catch { return null; }
}

export function normalizeConnectableUrl(raw: string, preferredHost = '127.0.0.1'): string {
  const url = new URL(raw);
  if (['0.0.0.0', '::', '[::]'].includes(url.hostname)) url.hostname = preferredHost;
  return url.toString().replace(/\/+$/, '');
}
export function normalizeApiBaseUrl(raw: string, preferredHost?: string): string {
  const value = normalizeConnectableUrl(raw, preferredHost);
  return value.endsWith('/api') ? value : `${value}/api`;
}

export function assertRuntimeGeneration(owner: number): void {
  if (owner !== generation) throw new DOMException('Connection changed', 'AbortError');
}
export function getRuntimeGeneration(): number { return generation; }
export function subscribeRuntimeReset(listener: () => void): () => void {
  resetListeners.add(listener);
  return () => { resetListeners.delete(listener); };
}

export function initializeRuntime(onProgress?: StartupProgressCallback): Promise<RuntimeConfig> {
  if (initialized) return Promise.resolve(runtimeConfig);
  if (initializing) return initializing;
  const owner = generation;
  const progress = (phase: StartupPhase) => { assertRuntimeGeneration(owner); onProgress?.(phase); };
  const run = async (): Promise<RuntimeConfig> => {
    if (!isTauriRuntime()) throw new Error('Desktop runtime requires Tauri shell');
    progress('spawning');
    const result = startSchema.parse(await invoke<unknown>('start_backend'));
    assertRuntimeGeneration(owner);
    const url = new URL(result.baseUrl);
    if ((result.mode === 'remote' && url.protocol !== 'https:')
      || (result.mode === 'local' && (url.protocol !== 'http:' || url.hostname !== '127.0.0.1'))
      || url.username || url.password || url.search || url.hash || url.pathname !== '/api') {
      throw new Error('Service returned an invalid API address');
    }
    runtimeConfig = {
      isDesktop: true, apiBaseUrl: result.baseUrl, sessionToken: result.sessionToken,
      serverId: result.serverId, profileId: result.profileId, mode: result.mode,
      dataEpoch: result.dataEpoch, expiresAtMs: result.expiresAtMs ?? undefined,
      apiPid: result.apiPid ?? undefined, runtimeWorkerPid: result.runtimeWorkerPid ?? undefined,
    };
    progress('waiting_for_worker');
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      const poll = pollSchema.parse(await invoke<unknown>('poll_backend_startup'));
      assertRuntimeGeneration(owner);
      if (poll.ready) {
        initialized = true;
        progress(poll.phase === 'recovering_data_clear' ? 'recovering_data_clear' : 'ready');
        return runtimeConfig;
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 500));
    }
    throw new Error('Backend startup timed out while waiting for the worker');
  };
  const pending = run().finally(() => { if (owner === generation) initializing = undefined; });
  initializing = pending;
  return pending;
}

/** Renew before dispatch; mutations are never automatically replayed after a response. */
export function ensureRuntimeSession(owner = generation): Promise<string | undefined> {
  assertRuntimeGeneration(owner);
  if (runtimeConfig.mode !== 'remote' || (runtimeConfig.expiresAtMs ?? 0) > Date.now() + 60_000) {
    return Promise.resolve(runtimeConfig.sessionToken);
  }
  if (renewing) return renewing;
  const profileId = runtimeConfig.profileId;
  const serverId = runtimeConfig.serverId;
  const pending = invoke<unknown>('renew_center_session', { profileId }).then((raw) => {
    assertRuntimeGeneration(owner);
    const session = sessionSchema.parse(raw);
    if (session.server_id !== serverId || session.expires_at_ms <= Date.now()) throw new Error('Center session identity or expiry is invalid');
    runtimeConfig = { ...runtimeConfig, sessionToken: session.access_token, expiresAtMs: session.expires_at_ms };
    return session.access_token;
  }).finally(() => { if (owner === generation) renewing = undefined; });
  renewing = pending;
  return pending;
}

export function resetRuntimeInitialization(): void {
  generation += 1;
  initialized = false;
  initializing = undefined;
  renewing = undefined;
  runtimeConfig = { isDesktop: true, apiBaseUrl: 'http://127.0.0.1:8000/api' };
  resetListeners.forEach((listener) => listener());
}
export function getRuntimeConfig(): RuntimeConfig { return runtimeConfig; }

export function setRuntimeDataEpoch(epoch: string): void { runtimeConfig = { ...runtimeConfig, dataEpoch: epoch }; }
