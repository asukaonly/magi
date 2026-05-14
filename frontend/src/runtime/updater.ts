import { getVersion } from '@tauri-apps/api/app';
import { relaunch } from '@tauri-apps/plugin-process';
import { check, type Update } from '@tauri-apps/plugin-updater';

import type { NetworkProxyConfig } from '../api/modules/config';

const AUTO_UPDATE_CHECK_AT_KEY = 'magi.desktop-updates.last-auto-check-at';

export const DEFAULT_UPDATE_CHECK_TIMEOUT_MS = 15_000;
export const DEFAULT_STARTUP_UPDATE_CHECK_DELAY_MS = 10_000;
export const DEFAULT_STARTUP_UPDATE_CHECK_COOLDOWN_MS = 6 * 60 * 60 * 1000;

let scheduledStartupCheckTimer: number | null = null;
let scheduledStartupCheckPromise: Promise<UpdateCheckResult | null> | null = null;

export interface UpdateCheckResult {
  currentVersion: string | null;
  update: Update | null;
}

export interface UpdateCheckOptions {
  proxy?: string;
  timeoutMs?: number;
  cancelScheduledStartupCheck?: boolean;
}

export interface StartupUpdateCheckOptions {
  network?: NetworkProxyConfig | null;
  delayMs?: number;
  cooldownMs?: number;
  timeoutMs?: number;
  onUpdateAvailable?: (result: UpdateCheckResult) => void;
  onError?: (error: unknown) => void;
}

function serializeUpdaterError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack ?? null,
    };
  }

  return {
    value: error,
  };
}

function summarizeUpdate(update: Update | null): Record<string, unknown> | null {
  if (!update) {
    return null;
  }

  return {
    version: update.version,
    date: update.date ?? null,
    bodyLength: update.body?.trim().length ?? 0,
  };
}

function readLastAutoCheckAt(): number | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    const rawValue = window.localStorage.getItem(AUTO_UPDATE_CHECK_AT_KEY);

    if (!rawValue) {
      return null;
    }

    const parsedValue = Number(rawValue);
    return Number.isFinite(parsedValue) ? parsedValue : null;
  } catch {
    return null;
  }
}

function writeLastAutoCheckAt(value: number): void {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.setItem(AUTO_UPDATE_CHECK_AT_KEY, String(value));
  } catch {
    // Ignore storage failures so update checks still work in restricted runtimes.
  }
}

function cancelScheduledStartupCheck(): void {
  if (scheduledStartupCheckTimer === null || typeof window === 'undefined') {
    return;
  }

  console.info('[updater] cancelling scheduled startup update check');

  window.clearTimeout(scheduledStartupCheckTimer);
  scheduledStartupCheckTimer = null;
  scheduledStartupCheckPromise = null;
}

export function buildUpdaterProxyUrl(network?: NetworkProxyConfig | null): string | undefined {
  if (!network?.enabled) {
    return undefined;
  }

  const host = network.host.trim();
  const port = Number(network.port);

  if (!host || !Number.isInteger(port) || port < 1 || port > 65_535) {
    return undefined;
  }

  return `${network.proxy_type}://${host}:${port}`;
}

export function isUpdaterRuntimeAvailable(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  return '__TAURI_INTERNALS__' in window || '__TAURI__' in window;
}

export async function getCurrentAppVersion(): Promise<string | null> {
  if (!isUpdaterRuntimeAvailable()) {
    console.info('[updater] current version unavailable because desktop runtime is not active');
    return null;
  }

  try {
    const version = await getVersion();
    console.info('[updater] resolved current app version', { currentVersion: version });
    return version;
  } catch (error) {
    console.warn('[updater] failed to resolve current app version', {
      error: serializeUpdaterError(error),
    });
    throw error;
  }
}

export async function checkForAppUpdate(options: UpdateCheckOptions = {}): Promise<UpdateCheckResult> {
  if (options.cancelScheduledStartupCheck !== false) {
    cancelScheduledStartupCheck();
  }

  if (!isUpdaterRuntimeAvailable()) {
    console.info('[updater] skipping update check because desktop runtime is not active');
    return {
      currentVersion: null,
      update: null,
    };
  }

  const proxy = options.proxy?.trim() || undefined;
  const timeout = options.timeoutMs ?? DEFAULT_UPDATE_CHECK_TIMEOUT_MS;

  console.info('[updater] checking for app update', {
    proxy: proxy ?? null,
    timeoutMs: timeout,
  });

  let currentVersion: string | null = null;
  try {
    currentVersion = await getVersion();
  } catch (error) {
    console.warn('[updater] continuing update check after current version lookup failed', {
      proxy: proxy ?? null,
      timeoutMs: timeout,
      error: serializeUpdaterError(error),
    });
  }

  try {
    const update = await check({ proxy, timeout });

    if (update) {
      console.info('[updater] update available', {
        currentVersion,
        proxy: proxy ?? null,
        timeoutMs: timeout,
        update: summarizeUpdate(update),
      });
    } else {
      console.info('[updater] no update available', {
        currentVersion,
        proxy: proxy ?? null,
        timeoutMs: timeout,
      });
    }

    return {
      currentVersion,
      update,
    };
  } catch (error) {
    console.error('[updater] update check failed', {
      currentVersion,
      proxy: proxy ?? null,
      timeoutMs: timeout,
      error: serializeUpdaterError(error),
    });
    throw error;
  }
}

export function scheduleStartupUpdateCheck(
  options: StartupUpdateCheckOptions = {}
): Promise<UpdateCheckResult | null> | null {
  if (!isUpdaterRuntimeAvailable() || typeof window === 'undefined') {
    console.info('[updater] skipping startup update scheduling because desktop runtime is not active');
    return null;
  }

  if (scheduledStartupCheckPromise) {
    console.info('[updater] reusing existing scheduled startup update check');
    return scheduledStartupCheckPromise;
  }

  const lastAutoCheckAt = readLastAutoCheckAt();
  const now = Date.now();
  const cooldownMs = options.cooldownMs ?? DEFAULT_STARTUP_UPDATE_CHECK_COOLDOWN_MS;

  if (lastAutoCheckAt !== null && now >= lastAutoCheckAt && now - lastAutoCheckAt < cooldownMs) {
    console.info('[updater] skipping startup update check because cooldown is still active', {
      cooldownMs,
      lastAutoCheckAt,
      nextEligibleAt: lastAutoCheckAt + cooldownMs,
    });
    return null;
  }

  const delayMs = options.delayMs ?? DEFAULT_STARTUP_UPDATE_CHECK_DELAY_MS;
  const proxy = buildUpdaterProxyUrl(options.network);
  const timeoutMs = options.timeoutMs ?? DEFAULT_UPDATE_CHECK_TIMEOUT_MS;

  console.info('[updater] scheduling startup update check', {
    delayMs,
    cooldownMs,
    proxy: proxy ?? null,
    timeoutMs,
  });

  scheduledStartupCheckPromise = new Promise((resolve) => {
    scheduledStartupCheckTimer = window.setTimeout(() => {
      scheduledStartupCheckTimer = null;
      writeLastAutoCheckAt(Date.now());

      console.info('[updater] running scheduled startup update check', {
        proxy: proxy ?? null,
        timeoutMs,
      });

      void checkForAppUpdate({
        proxy,
        timeoutMs,
        cancelScheduledStartupCheck: false,
      })
        .then((result) => {
          console.info('[updater] scheduled startup update check completed', {
            currentVersion: result.currentVersion,
            update: summarizeUpdate(result.update),
          });
          if (result.update) {
            options.onUpdateAvailable?.(result);
          }
          resolve(result);
        })
        .catch((error) => {
          console.error('[updater] scheduled startup update check failed', {
            proxy: proxy ?? null,
            timeoutMs,
            error: serializeUpdaterError(error),
          });
          options.onError?.(error);
          resolve(null);
        })
        .finally(() => {
          scheduledStartupCheckPromise = null;
        });
    }, delayMs);
  });

  return scheduledStartupCheckPromise;
}

export async function restartToApplyUpdate(): Promise<void> {
  if (!isUpdaterRuntimeAvailable()) {
    return;
  }

  await relaunch();
}
