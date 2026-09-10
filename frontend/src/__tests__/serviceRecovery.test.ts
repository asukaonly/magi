import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  listen: vi.fn(), invoke: vi.fn(), reconnect: vi.fn(), generation: 1,
  runtime: { mode: 'local', profileId: 'local', connectionGeneration: 1 },
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: mocks.listen }));
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }));
vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => mocks.runtime,
  getRuntimeGeneration: () => mocks.generation,
  isTauriRuntime: () => true,
  requestRuntimeReconnect: mocks.reconnect,
}));
import { observeLocalServiceRecovery } from '@/runtime/service-recovery';

let receive: (event: { payload: unknown }) => void;
let stop: (() => void) | undefined;
const snapshot = (generation = 1) => ({ generation, profileId: 'local', mode: 'local', recovering: false });
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
beforeEach(() => {
  vi.useFakeTimers();
  mocks.reconnect.mockReset(); mocks.invoke.mockReset(); mocks.generation = 1;
  mocks.runtime = { mode: 'local', profileId: 'local', connectionGeneration: 1 };
  mocks.invoke.mockResolvedValue(snapshot());
  mocks.listen.mockImplementation(async (_name, callback) => { receive = callback; return vi.fn(); });
});
afterEach(() => { stop?.(); stop = undefined; vi.useRealTimers(); vi.restoreAllMocks(); });
const recovered = { profileId: 'local', previousPid: 42, localServicePid: 43 };

describe('desktop service recovery observation', () => {
  it('uses events as hints and reconnects from the current native generation', async () => {
    stop = observeLocalServiceRecovery(); await flush();
    receive({ payload: recovered }); await flush();
    expect(mocks.reconnect).not.toHaveBeenCalled();
    mocks.invoke.mockResolvedValue(snapshot(3));
    receive({ payload: { ...recovered, previousPid: 10 } }); await flush();
    expect(mocks.reconnect).toHaveBeenCalledOnce();
  });
  it('reconciles missed events on a timer and window focus', async () => {
    stop = observeLocalServiceRecovery(); await flush();
    mocks.invoke.mockResolvedValue(snapshot(2));
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mocks.reconnect).toHaveBeenCalledOnce();
    mocks.runtime.connectionGeneration = 2;
    mocks.invoke.mockResolvedValue(snapshot(3));
    window.dispatchEvent(new Event('focus')); await flush();
    expect(mocks.reconnect).toHaveBeenCalledTimes(2);
  });
  it('keeps polling after listener registration or native snapshot failure', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    mocks.listen.mockRejectedValue(new Error('registration failed'));
    mocks.invoke.mockRejectedValueOnce(new Error('native unavailable')).mockResolvedValue(snapshot(2));
    stop = observeLocalServiceRecovery(); await flush();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mocks.reconnect).toHaveBeenCalledOnce();
  });
  it('does not reconnect during recovery or after a profile switch', async () => {
    mocks.invoke.mockResolvedValue({ ...snapshot(2), recovering: true });
    stop = observeLocalServiceRecovery(); await flush();
    expect(mocks.reconnect).not.toHaveBeenCalled();
    let finish: (value: unknown) => void = () => undefined;
    mocks.invoke.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('focus'));
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
    mocks.generation += 1;
    finish(snapshot(3)); await flush();
    expect(mocks.reconnect).not.toHaveBeenCalled();
    mocks.runtime.mode = 'remote';
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
  });
  it('cleans up late registration without polling after unmount', async () => {
    let finishRegistration: (cleanup: () => void) => void = () => undefined;
    const cleanup = vi.fn();
    mocks.listen.mockImplementation((_name, callback) => {
      receive = callback;
      return new Promise((resolve) => { finishRegistration = resolve; });
    });
    stop = observeLocalServiceRecovery(); stop();
    receive({ payload: recovered }); finishRegistration(cleanup); await flush();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(cleanup).toHaveBeenCalledOnce();
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.reconnect).not.toHaveBeenCalled();
  });
});
