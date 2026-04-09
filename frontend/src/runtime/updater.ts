import { getVersion } from '@tauri-apps/api/app';
import { relaunch } from '@tauri-apps/plugin-process';
import { check, type Update } from '@tauri-apps/plugin-updater';

export interface UpdateCheckResult {
  currentVersion: string | null;
  update: Update | null;
}

export function isUpdaterRuntimeAvailable(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  return '__TAURI_INTERNALS__' in window || '__TAURI__' in window;
}

export async function getCurrentAppVersion(): Promise<string | null> {
  if (!isUpdaterRuntimeAvailable()) {
    return null;
  }

  return getVersion();
}

export async function checkForAppUpdate(): Promise<UpdateCheckResult> {
  if (!isUpdaterRuntimeAvailable()) {
    return {
      currentVersion: null,
      update: null,
    };
  }

  const [currentVersion, update] = await Promise.all([
    getVersion(),
    check(),
  ]);

  return {
    currentVersion,
    update,
  };
}

export async function restartToApplyUpdate(): Promise<void> {
  if (!isUpdaterRuntimeAvailable()) {
    return;
  }

  await relaunch();
}
