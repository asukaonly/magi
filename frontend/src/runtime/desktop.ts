export const DESKTOP_OPEN_SETTINGS_EVENT = 'desktop-presence://open-settings';
export const DESKTOP_QUIT_REQUESTED_EVENT = 'desktop-presence://quit-requested';

export interface DesktopShellHandlers {
  onOpenSettings: () => void;
  onRequestQuit: () => void;
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

  const { invoke } = await import('@tauri-apps/api/core');
  if (payload) {
    return invoke<T>(command, payload);
  }
  return invoke<T>(command);
}

export async function registerDesktopShellHandlers(handlers: DesktopShellHandlers): Promise<Unlisten> {
  if (!isTauriRuntime()) {
    return async () => {};
  }

  const { listen } = await import('@tauri-apps/api/event');
  const unlistenCallbacks = await Promise.all([
    listen(DESKTOP_OPEN_SETTINGS_EVENT, () => {
      handlers.onOpenSettings();
    }),
    listen(DESKTOP_QUIT_REQUESTED_EVENT, () => {
      handlers.onRequestQuit();
    }),
  ]);

  return async () => {
    await Promise.all(unlistenCallbacks.map((unlisten) => unlisten()));
  };
}

export async function syncCloseToTrayPreference(enabled: boolean): Promise<void> {
  await invokeDesktopCommand('set_close_to_tray_enabled', { enabled });
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

export async function confirmExitApp(): Promise<void> {
  await invokeDesktopCommand('confirm_exit_app');
}

export async function cancelExitRequest(): Promise<void> {
  await invokeDesktopCommand('cancel_exit_request');
}
