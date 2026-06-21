import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getVersionMock = vi.fn();
const checkMock = vi.fn();
const relaunchMock = vi.fn();

vi.mock('@tauri-apps/api/app', () => ({
  getVersion: getVersionMock,
}));

vi.mock('@tauri-apps/plugin-process', () => ({
  relaunch: relaunchMock,
}));

vi.mock('@tauri-apps/plugin-updater', () => ({
  check: checkMock,
}));

type TauriWindow = Window & {
  __TAURI__?: object;
  __TAURI_INTERNALS__?: object;
};

function createStorage(): Storage {
  const values = new Map<string, string>();

  return {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key: string) {
      return values.has(key) ? values.get(key)! : null;
    },
    key(index: number) {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string) {
      values.delete(key);
    },
    setItem(key: string, value: string) {
      values.set(key, String(value));
    },
  };
}

async function loadUpdaterModule() {
  vi.resetModules();
  return import('@/runtime/updater');
}

describe('updater runtime', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    getVersionMock.mockReset();
    checkMock.mockReset();
    relaunchMock.mockReset();
    const storage = createStorage();
    vi.stubGlobal('localStorage', storage);
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: storage,
    });
    delete (window as TauriWindow).__TAURI__;
    delete (window as TauriWindow).__TAURI_INTERNALS__;
    (window as TauriWindow).__TAURI_INTERNALS__ = {};
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('builds a proxy URL from the global network proxy settings', async () => {
    const { buildUpdaterProxyUrl } = await loadUpdaterModule();

    expect(buildUpdaterProxyUrl({
      enabled: true,
      proxy_type: 'socks5',
      host: '127.0.0.1',
      port: 7890,
      username: '',
      password: '',
    })).toBe('socks5://127.0.0.1:7890');

    expect(buildUpdaterProxyUrl({
      enabled: true,
      proxy_type: 'http',
      host: 'proxy.example.test',
      port: 8080,
      username: 'magi user',
      password: 'pa:ss@word',
    })).toBe('http://magi%20user:pa%3Ass%40word@proxy.example.test:8080');

    expect(buildUpdaterProxyUrl({
      enabled: false,
      proxy_type: 'http',
      host: '127.0.0.1',
      port: 7890,
      username: '',
      password: '',
    })).toBeUndefined();
  });

  it('passes proxy and timeout to the updater check call', async () => {
    getVersionMock.mockResolvedValue('0.1.2');
    checkMock.mockResolvedValue(null);

    const { checkForAppUpdate } = await loadUpdaterModule();
    const result = await checkForAppUpdate({
      proxy: 'http://127.0.0.1:7890',
      timeoutMs: 4321,
    });

    expect(checkMock).toHaveBeenCalledWith({
      proxy: 'http://127.0.0.1:7890',
      timeout: 4321,
    });
    expect(result).toEqual({
      currentVersion: '0.1.2',
      update: null,
    });
  });

  it('schedules one startup background check and respects the cooldown window', async () => {
    vi.useFakeTimers();
    getVersionMock.mockResolvedValue('0.1.2');
    checkMock.mockResolvedValue(null);

    const {
      DEFAULT_UPDATE_CHECK_TIMEOUT_MS,
      scheduleStartupUpdateCheck,
    } = await loadUpdaterModule();

    const scheduledCheck = scheduleStartupUpdateCheck({
      network: {
        enabled: true,
        proxy_type: 'http',
        host: '127.0.0.1',
        port: 7890,
        username: '',
        password: '',
      },
      delayMs: 25,
      cooldownMs: 60_000,
    });

    expect(scheduledCheck).not.toBeNull();
    expect(checkMock).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(25);
    await scheduledCheck!;

    expect(checkMock).toHaveBeenCalledWith({
      proxy: 'http://127.0.0.1:7890',
      timeout: DEFAULT_UPDATE_CHECK_TIMEOUT_MS,
    });
    expect(scheduleStartupUpdateCheck({ cooldownMs: 60_000 })).toBeNull();
  });
});
