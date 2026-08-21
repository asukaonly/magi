import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

export const DESKTOP_OPEN_SETTINGS_EVENT = 'desktop-presence://open-settings';
export const DESKTOP_QUIT_REQUESTED_EVENT = 'desktop-presence://quit-requested';

export interface DesktopLogClearResult {
  clearedEntries: number;
  failedEntries: number;
}

export interface PendingFullDataClear {
  version: number;
  transactionId: string;
}

type Unlisten = () => void | Promise<void>;

function isTauriRuntime(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  return '__TAURI_INTERNALS__' in window || '__TAURI__' in window;
}

async function invokeDesktopCommand<T = void>(command: string, payload?: Record<string, unknown>): Promise<T | undefined> {
  if (!isTauriRuntime()) {
    return undefined;
  }

  if (payload) {
    return invoke<T>(command, payload);
  }
  return invoke<T>(command);
}

async function registerDesktopEventHandler(eventName: string, handler: () => void): Promise<Unlisten> {
  if (!isTauriRuntime()) {
    return async () => {};
  }

  return listen(eventName, handler);
}

export async function registerDesktopOpenSettingsHandler(handler: () => void): Promise<Unlisten> {
  return registerDesktopEventHandler(DESKTOP_OPEN_SETTINGS_EVENT, handler);
}

export async function registerDesktopQuitHandler(handler: () => void): Promise<Unlisten> {
  return registerDesktopEventHandler(DESKTOP_QUIT_REQUESTED_EVENT, handler);
}

export async function syncCloseToTrayPreference(enabled: boolean): Promise<void> {
  await invokeDesktopCommand('set_close_to_tray_enabled', { enabled });
}

export async function syncAutoStartPreference(enabled: boolean): Promise<void> {
  if (!isTauriRuntime()) {
    return;
  }
  try {
    const { enable, disable } = await import('@tauri-apps/plugin-autostart');
    if (enabled) {
      await enable();
    } else {
      await disable();
    }
  } catch {
    // autostart plugin unavailable in dev mode
  }
}

export async function syncStartMinimizedPreference(enabled: boolean): Promise<void> {
  await invokeDesktopCommand('set_start_minimized', { enabled });
}

export async function syncSkipQuitConfirmationPreference(enabled: boolean): Promise<void> {
  await invokeDesktopCommand('set_skip_quit_confirmation', { enabled });
}

export async function applyStartMinimized(): Promise<void> {
  await invokeDesktopCommand('apply_start_minimized');
}

export async function pickDirectory(defaultPath?: string | null): Promise<string | undefined> {
  if (!isTauriRuntime()) {
    return undefined;
  }

  const { open } = await import('@tauri-apps/plugin-dialog');
  const selection = await open({
    directory: true,
    multiple: false,
    defaultPath: defaultPath || undefined,
  });

  if (Array.isArray(selection) || !selection) {
    return undefined;
  }
  return selection;
}

export async function pickFile(defaultPath?: string | null): Promise<string | undefined> {
  if (!isTauriRuntime()) {
    return undefined;
  }

  const { open } = await import('@tauri-apps/plugin-dialog');
  const selection = await open({
    directory: false,
    multiple: false,
    defaultPath: defaultPath || undefined,
  });

  if (Array.isArray(selection) || !selection) {
    return undefined;
  }
  return selection;
}

export async function pickMarkdownFiles(): Promise<string[]> {
  if (!isTauriRuntime()) {
    return [];
  }

  const { open } = await import('@tauri-apps/plugin-dialog');
  const selection = await open({
    directory: false,
    multiple: true,
    filters: [
      {
        name: 'Markdown',
        extensions: ['md', 'markdown'],
      },
    ],
  });

  if (!selection) {
    return [];
  }
  return Array.isArray(selection) ? selection : [selection];
}

export async function pickHistoryImportFiles(
  extensions: string[],
  filterName: string,
): Promise<string[]> {
  if (!isTauriRuntime()) {
    return [];
  }

  const normalizedExtensions = [...new Set(
    extensions
      .map((extension) => String(extension || '').trim().replace(/^\./, '').toLowerCase())
      .filter(Boolean),
  )];
  const { open } = await import('@tauri-apps/plugin-dialog');
  const selection = await open({
    directory: false,
    multiple: true,
    filters: normalizedExtensions.length > 0
      ? [
          {
            name: filterName,
            extensions: normalizedExtensions,
          },
        ]
      : undefined,
  });

  if (!selection) {
    return [];
  }
  return Array.isArray(selection) ? selection : [selection];
}

export async function openExternalUrl(url: string): Promise<void> {
  const normalizedUrl = String(url || '').trim();
  if (!normalizedUrl) {
    return;
  }

  if (isTauriRuntime()) {
    // The desktop host validates the scheme and opens it through the operating
    // system without involving a command interpreter.
    await invokeDesktopCommand('open_url', { url: normalizedUrl });
    return;
  }

  window.open(normalizedUrl, '_blank', 'noopener,noreferrer');
}

export async function clearDesktopLogHistory(): Promise<DesktopLogClearResult | undefined> {
  return invokeDesktopCommand<DesktopLogClearResult>('clear_desktop_log_history');
}

export async function beginFullDataClear(): Promise<PendingFullDataClear | undefined> {
  return invokeDesktopCommand<PendingFullDataClear>('begin_full_data_clear');
}

export async function readPendingFullDataClear(): Promise<PendingFullDataClear | null | undefined> {
  return invokeDesktopCommand<PendingFullDataClear | null>('read_pending_full_data_clear');
}

export async function completeFullDataClear(transactionId: string): Promise<void> {
  if (!isTauriRuntime()) {
    throw new Error('Desktop full data clear owner is unavailable');
  }
  await invokeDesktopCommand('complete_full_data_clear', { transactionId });
}

export async function confirmExitApp(): Promise<void> {
  await invokeDesktopCommand('confirm_exit_app');
}

export async function cancelExitRequest(): Promise<void> {
  await invokeDesktopCommand('cancel_exit_request');
}

function hslToRgb(h: number, s: number, l: number): { r: number; g: number; b: number } {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const hp = ((h % 360) + 360) % 360 / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let r1 = 0;
  let g1 = 0;
  let b1 = 0;
  if (hp < 1) { r1 = c; g1 = x; }
  else if (hp < 2) { r1 = x; g1 = c; }
  else if (hp < 3) { g1 = c; b1 = x; }
  else if (hp < 4) { g1 = x; b1 = c; }
  else if (hp < 5) { r1 = x; b1 = c; }
  else { r1 = c; b1 = x; }
  const m = l - c / 2;
  return {
    r: Math.round((r1 + m) * 255),
    g: Math.round((g1 + m) * 255),
    b: Math.round((b1 + m) * 255),
  };
}

export async function syncWindowCaptionColor(): Promise<void> {
  if (!isTauriRuntime() || typeof window === 'undefined' || typeof document === 'undefined') {
    return;
  }
  // `--background` is stored as space-separated HSL components (e.g. "30 25% 97%").
  const raw = window
    .getComputedStyle(document.documentElement)
    .getPropertyValue('--background')
    .trim();
  if (!raw) {
    return;
  }
  const parts = raw.split(/\s+/);
  if (parts.length < 3) {
    return;
  }
  const h = Number.parseFloat(parts[0]);
  const s = Number.parseFloat(parts[1]) / 100;
  const l = Number.parseFloat(parts[2]) / 100;
  if (!Number.isFinite(h) || !Number.isFinite(s) || !Number.isFinite(l)) {
    return;
  }
  const { r, g, b } = hslToRgb(h, s, l);
  try {
    await invokeDesktopCommand('set_window_caption_color', { r, g, b });
  } catch {
    // ignore; only supported on Windows 10 22H2+/11
  }
}
