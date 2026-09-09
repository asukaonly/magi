import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ listen: vi.fn(), reconnect: vi.fn(), runtime: { mode: 'local', profileId: 'local', localServicePid: 42 } }));
vi.mock('@tauri-apps/api/event', () => ({ listen: mocks.listen }));
vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => mocks.runtime,
  isTauriRuntime: () => true,
  requestRuntimeReconnect: mocks.reconnect,
}));
import { observeLocalServiceRecovery } from '@/runtime/service-recovery';

let receive: (event: { payload: unknown }) => void;
beforeEach(() => {
  mocks.reconnect.mockReset();
  mocks.runtime = { mode: 'local', profileId: 'local', localServicePid: 42 };
  mocks.listen.mockImplementation(async (_name, callback) => { receive = callback; return vi.fn(); });
});
const recovered = { profileId: 'local', previousPid: 42, localServicePid: 43 };

describe('desktop service recovery observation', () => {
  it('rebuilds the connection only for its current owned process', () => {
    const stop = observeLocalServiceRecovery();
    receive({ payload: recovered });
    expect(mocks.reconnect).toHaveBeenCalledOnce();
    stop();
  });
  it('ignores old processes, remote profiles and malformed events', () => {
    const stop = observeLocalServiceRecovery();
    receive({ payload: { ...recovered, previousPid: 40 } });
    mocks.runtime.mode = 'remote';
    receive({ payload: recovered });
    receive({ payload: { profileId: 'local' } });
    expect(mocks.reconnect).not.toHaveBeenCalled();
    stop();
  });
  it('cleans up a registration that finishes after the bootstrap unmounts', async () => {
    let finish: (cleanup: () => void) => void = () => undefined;
    const cleanup = vi.fn();
    mocks.listen.mockImplementation((_name, callback) => {
      receive = callback;
      return new Promise((resolve) => { finish = resolve; });
    });
    const stop = observeLocalServiceRecovery();
    stop();
    receive({ payload: recovered });
    finish(cleanup);
    await Promise.resolve();
    expect(cleanup).toHaveBeenCalledOnce();
    expect(mocks.reconnect).not.toHaveBeenCalled();
  });
});
