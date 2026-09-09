import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';

export interface RuntimeConfig {
  isDesktop: boolean;
  apiBaseUrl: string;
  sessionToken?: string;
  localServicePid?: number;
  serverId?: string;
  profileId?: string;
  mode?: 'local' | 'remote';
  dataEpoch?: string;
  contentEpoch?: string;
  expiresAtMs?: number;
}

const connectionSchema = z.object({
  ok: z.literal(true), baseUrl: z.string().url(), sessionToken: z.string().min(32).max(256),
  serverId: z.string().uuid(), profileId: z.string().min(1), mode: z.enum(['local', 'remote']),
  contentEpoch: z.string().min(1).max(128),
  dataEpoch: z.string().min(1).max(128), expiresAtMs: z.number().int().nullable(),
  localServicePid: z.number().int().nullable(),
});
const pollSchema = z.object({ ready: z.boolean(), phase: z.string() });
const sessionSchema = z.object({
  server_id: z.string().uuid(), client_id: z.string().uuid(),
  access_token: z.string().min(32).max(256), expires_at_ms: z.number().int(),
});
const diagnosticsSchema = z.object({
  logPath: z.string().nullish(), logExcerpt: z.string().nullish(), logReadError: z.string().nullish(),
});
export interface ConnectionStartupDiagnostics {
  logPath?: string;
  logExcerpt?: string;
  logReadError?: string;
}
export type StartupPhase = 'waiting_for_worker' | 'connecting' | 'recovering_maintenance' | 'ready' | 'error';
export type StartupProgressCallback = (phase: StartupPhase) => void;

let runtimeConfig: RuntimeConfig = { isDesktop: true, apiBaseUrl: 'http://127.0.0.1:8000/api' };
let initialized = false;
let generation = 0;
let initializing: Promise<RuntimeConfig> | undefined;
let renewing: Promise<string | undefined> | undefined;
let renewalFailure: { until: number; error: unknown } | undefined;
const resetListeners = new Set<() => void>();
const reconnectListeners = new Set<() => void>();

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

export async function readConnectionStartupDiagnostics(): Promise<ConnectionStartupDiagnostics | null> {
  if (!isTauriRuntime()) return null;
  try {
    const result = diagnosticsSchema.parse(await invoke<unknown>('read_connection_startup_diagnostics'));
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
    progress('connecting');
    const result = connectionSchema.parse(await invoke<unknown>('connect_active_profile'));
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
      contentEpoch: result.contentEpoch, dataEpoch: result.dataEpoch, expiresAtMs: result.expiresAtMs ?? undefined,
      localServicePid: result.localServicePid ?? undefined,
    };
    progress(result.mode === 'local' ? 'waiting_for_worker' : 'connecting');
    const deadline = Date.now() + 180_000;
    while (Date.now() < deadline) {
      const poll = pollSchema.parse(await invoke<unknown>('poll_connection_startup'));
      assertRuntimeGeneration(owner);
      if (poll.ready) {
        initialized = true;
        progress(poll.phase === 'recovering_maintenance' ? 'recovering_maintenance' : 'ready');
        return runtimeConfig;
      }
      await new Promise<void>((resolve) => window.setTimeout(resolve, 500));
    }
    throw new Error('Magi service readiness timed out');
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
  if (renewalFailure && Date.now() < renewalFailure.until) return Promise.reject(renewalFailure.error);
  const profileId = runtimeConfig.profileId;
  const serverId = runtimeConfig.serverId;
  const pending = invoke<unknown>('renew_center_session', { profileId }).then((raw) => {
    assertRuntimeGeneration(owner);
    const session = sessionSchema.parse(raw);
    if (session.server_id !== serverId || session.expires_at_ms <= Date.now()) throw new Error('Center session identity or expiry is invalid');
    runtimeConfig = { ...runtimeConfig, sessionToken: session.access_token, expiresAtMs: session.expires_at_ms };
    renewalFailure = undefined;
    return session.access_token;
  }).catch((error: unknown) => {
    if (owner === generation) renewalFailure = { until: Date.now() + 5_000, error };
    throw error;
  }).finally(() => { if (owner === generation) renewing = undefined; });
  renewing = pending;
  return pending;
}

/** An old 401 must not invalidate a newer session or another connection. */
export function recoverRuntimeSession(rejectedToken: string | undefined, owner: number): Promise<string | undefined> {
  assertRuntimeGeneration(owner);
  if (runtimeConfig.mode !== 'remote') return Promise.resolve(undefined);
  if (rejectedToken === runtimeConfig.sessionToken) {
    runtimeConfig = { ...runtimeConfig, expiresAtMs: 0 };
  }
  return ensureRuntimeSession(owner);
}

export function resetRuntimeInitialization(): void {
  generation += 1;
  initialized = false;
  initializing = undefined;
  renewing = undefined;
  renewalFailure = undefined;
  runtimeConfig = { isDesktop: true, apiBaseUrl: 'http://127.0.0.1:8000/api' };
  resetListeners.forEach((listener) => listener());
}
export function getRuntimeConfig(): RuntimeConfig { return runtimeConfig; }

export function setRuntimeEpochs(dataEpoch: string, contentEpoch: string): void { runtimeConfig = { ...runtimeConfig, dataEpoch, contentEpoch }; }

/** The app bootstrap owns rebuilding API clients, event streams and mounted views. */
export function subscribeRuntimeReconnect(listener: () => void): () => void {
  reconnectListeners.add(listener);
  return () => { reconnectListeners.delete(listener); };
}

export function requestRuntimeReconnect(): void {
  resetRuntimeInitialization();
  reconnectListeners.forEach((listener) => listener());
}
