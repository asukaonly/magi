import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const { runtime, server, cleanup, logs, configure, invalidateOffline, runtimeOwner } = vi.hoisted(() => ({
  runtime: { serverId: 'center-a', dataEpoch: 'original', contentEpoch: 'original', apiBaseUrl: 'https://center.example/api', sessionToken: 'token' },
  server: { clear: vi.fn(), restore: vi.fn(), maintenance: vi.fn(), operation: vi.fn(), info: vi.fn() }, cleanup: vi.fn(), logs: vi.fn(), configure: vi.fn(),
  invalidateOffline: vi.fn(), runtimeOwner: { generation: 1 },
}));
vi.mock('@/api/modules/server', () => ({ serverApi: server }));
vi.mock('@/api/client', () => ({ configureApiClient: configure }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => runtime, getRuntimeGeneration: () => runtimeOwner.generation, assertRuntimeGeneration: (owner: number) => { if (owner !== runtimeOwner.generation) throw new Error('Connection changed'); }, subscribeRuntimeReset: vi.fn(), setRuntimeEpochs: (epoch: string, content: string) => { runtime.dataEpoch = epoch; runtime.contentEpoch = content; } }));
vi.mock('@/runtime/offline-connection', () => ({ invalidateOfflineConnection: invalidateOffline }));
vi.mock('@/runtime/desktop', () => ({ clearDesktopLogHistory: logs }));
vi.mock('@/hooks/chatRetryLifecycle', () => ({ completeMemoryClear: cleanup }));
import { clearAllMemory, confirmCenterRestore, recoverPendingCenterMaintenance } from '@/hooks/clearAllMemory';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import { APP_EVENTS } from '@/constants/events';
const results = Object.fromEntries(['l0', 'l1', 'l2', 'l3', 'l4', 'chat_context'].map((area) => [area, { cleared: true, count: 2 }]));
const receipt = { success: true, results, warnings: [] };
const status = (operationId: string, phase = 'completed') => ({ version: 2, kind: 'clear', content_epoch: phase === 'completed' ? operationId : 'original', operation_id: operationId, phase, data_epoch: phase === 'completed' ? operationId : 'original', result: phase === 'completed' ? receipt : null, error: phase === 'failed' ? 'Worker failed' : null });
function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('center-owned full clear', () => {
  beforeEach(() => {
    vi.clearAllMocks(); window.localStorage.clear(); window.sessionStorage.clear(); runtime.dataEpoch = 'original'; runtime.contentEpoch = 'original';
    runtimeOwner.generation = 1;
    invalidateOffline.mockReset().mockResolvedValue(undefined);
    setCenterStorageScope(runtime.serverId, 'original');
    cleanup.mockReturnValue({ browserStateCleared: true, failedScopes: [] });
    logs.mockResolvedValue({ clearedEntries: 1, failedEntries: 0 });
    server.clear.mockImplementation(async (id: string) => status(id));
    server.operation.mockImplementation(async (id: string) => status(id));
    server.info.mockImplementation(async () => { const id = server.clear.mock.calls.at(-1)?.[0] ?? 'remote-operation'; return { service_ready: true, maintenance: status(id) }; });
  });
  afterEach(() => vi.useRealTimers());
  it('deduplicates concurrent clear actions and cleans this device after center completion', async () => {
    const first = clearAllMemory(); const second = clearAllMemory(); expect(second).toBe(first);
    await expect(first).resolves.toEqual(receipt);
    expect(server.clear).toHaveBeenCalledOnce(); expect(cleanup).toHaveBeenCalledOnce(); expect(logs).toHaveBeenCalledOnce();
    expect(centerLocalStorage().getItem('maintenance.pending-clear')).toBeNull();
  });
  it('retains the operation ID when the network reply is uncertain and reuses it on retry', async () => {
    server.clear.mockRejectedValueOnce(new Error('Connection lost'));
    await expect(clearAllMemory()).rejects.toThrow('Connection lost');
    const id = centerLocalStorage().getItem('maintenance.pending-clear'); expect(id).toBeTruthy();
    await clearAllMemory(); expect(server.clear).toHaveBeenLastCalledWith(id);
  });
  it('observes an operation started by another device through completion', async () => {
    vi.useFakeTimers(); server.maintenance.mockResolvedValueOnce(status('remote-operation', 'clearing')).mockResolvedValue(status('remote-operation'));
    const pending = recoverPendingCenterMaintenance(); await vi.runAllTimersAsync();
    await expect(pending).resolves.toBe(true); expect(server.clear).not.toHaveBeenCalled();
  });
  it('does not resubmit a failed center operation without an explicit retry', async () => {
    server.maintenance.mockResolvedValue(status('remote-operation', 'failed'));
    await expect(recoverPendingCenterMaintenance()).rejects.toThrow('Worker failed'); expect(server.clear).not.toHaveBeenCalled();
    await expect(recoverPendingCenterMaintenance(true)).resolves.toBe(true); expect(server.clear).toHaveBeenCalledWith('remote-operation');
  });
  it('keeps device cleanup pending if diagnostic log cleanup fails, without rerunning center deletion', async () => {
    logs.mockResolvedValueOnce({ clearedEntries: 0, failedEntries: 1 });
    await expect(clearAllMemory()).rejects.toThrow('diagnostic logs');
    expect(centerLocalStorage().getItem('maintenance.device-cleanup')).toBe('pending');
    server.maintenance.mockResolvedValue(status(server.clear.mock.calls.at(-1)?.[0]));
    await recoverPendingCenterMaintenance(); expect(server.clear).toHaveBeenCalledOnce(); expect(logs).toHaveBeenCalledTimes(2);
    expect(centerLocalStorage().getItem('maintenance.device-cleanup')).toBeNull();
  });
  it('rejects incomplete center receipts before releasing the product gate', async () => {
    const released = vi.fn(); window.addEventListener(APP_EVENTS.MEMORY_CLEARED, released);
    server.clear.mockImplementation(async (id: string) => ({ ...status(id), result: { ...receipt, results: { ...results, l0: { cleared: false, count: 0 } } } }));
    await expect(clearAllMemory()).rejects.toThrow(); expect(cleanup).not.toHaveBeenCalled(); expect(released).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, released);
  });
  it('restores memory without deleting conversation caches or device logs', async () => {
    const restored = { ...status('restore-operation'), kind: 'restore', content_epoch: 'original', result: { success: true, rollback_performed: false } };
    centerLocalStorage().setItem('chat_session_active', 'keep-this-session');
    server.restore.mockResolvedValue(restored);
    server.info.mockResolvedValue({ service_ready: true, maintenance: restored });
    await confirmCenterRestore('restore-operation');
    expect(runtime.dataEpoch).toBe('restore-operation');
    expect(runtime.contentEpoch).toBe('original');
    expect(centerLocalStorage().getItem('chat_session_active')).toBe('keep-this-session');
    expect(cleanup).not.toHaveBeenCalled(); expect(logs).not.toHaveBeenCalled();
    expect(centerLocalStorage().getItem('maintenance.pending-restore')).toBeNull();
  });
  it('reads the original clear receipt after newer maintenance without resubmitting it', async () => {
    const newer = { ...status('new-restore'), kind: 'restore', content_epoch: 'previous-clear', result: { success: true } };
    centerLocalStorage().setItem('maintenance.pending-clear', 'previous-clear');
    server.maintenance.mockResolvedValue(newer);
    server.operation.mockResolvedValue({ ...status('previous-clear'), data_epoch: 'new-restore', content_epoch: 'previous-clear' });
    server.info.mockResolvedValue({ service_ready: true, maintenance: newer });
    await recoverPendingCenterMaintenance();
    expect(server.operation).toHaveBeenCalledWith('previous-clear');
    expect(server.clear).not.toHaveBeenCalled();
    expect(runtime.dataEpoch).toBe('new-restore');
    expect(runtime.contentEpoch).toBe('previous-clear');
  });
  it('cleans an offline device after a missed full clear followed by a memory restore', async () => {
    server.maintenance.mockResolvedValue({ ...status('new-restore'), kind: 'restore', content_epoch: 'missed-clear', result: { success: true } });
    await recoverPendingCenterMaintenance();
    expect(cleanup).toHaveBeenCalledOnce();
    expect(runtime.contentEpoch).toBe('missed-clear');
    expect(server.clear).not.toHaveBeenCalled(); expect(server.restore).not.toHaveBeenCalled();
  });

  it.each(['clear', 'restore'] as const)('waits for durable offline invalidation before admitting %s', async (kind) => {
    const gate = deferred<void>();
    invalidateOffline.mockReturnValueOnce(gate.promise);
    const restored = { ...status('restore-operation'), kind: 'restore', content_epoch: 'original', result: { success: true } };
    server.restore.mockResolvedValue(restored);
    if (kind === 'restore') server.info.mockResolvedValue({ service_ready: true, maintenance: restored });
    const pending = kind === 'clear' ? clearAllMemory() : confirmCenterRestore('restore-operation');
    expect(invalidateOffline).toHaveBeenCalledOnce();
    expect(server.clear).not.toHaveBeenCalled();
    expect(server.restore).not.toHaveBeenCalled();
    expect(centerLocalStorage().getItem(`maintenance.pending-${kind}`)).toBeNull();
    gate.resolve();
    await pending;
    expect(server[kind]).toHaveBeenCalledOnce();
  });

  it.each(['clear', 'restore'] as const)('rejects %s when offline invalidation cannot persist', async (kind) => {
    invalidateOffline.mockRejectedValueOnce(new Error('Could not suspend saved content access'));
    const pending = kind === 'clear' ? clearAllMemory() : confirmCenterRestore('restore-operation');
    await expect(pending).rejects.toThrow('Could not suspend saved content access');
    expect(server.clear).not.toHaveBeenCalled();
    expect(server.restore).not.toHaveBeenCalled();
    expect(centerLocalStorage().getItem(`maintenance.pending-${kind}`)).toBeNull();
  });

  it('invalidates before resuming an operation whose response was lost', async () => {
    centerLocalStorage().setItem('maintenance.pending-clear', 'lost-operation');
    server.maintenance.mockResolvedValue({ ...status('original'), kind: null, phase: 'idle', operation_id: null, result: null });
    const gate = deferred<void>();
    invalidateOffline.mockReturnValueOnce(gate.promise);
    const pending = recoverPendingCenterMaintenance(true);
    await vi.waitFor(() => expect(invalidateOffline).toHaveBeenCalledOnce());
    expect(server.clear).not.toHaveBeenCalled();
    gate.resolve();
    await pending;
    expect(server.clear).toHaveBeenCalledWith('lost-operation');
  });

  it('invalidates changed data epochs even when restore preserves the content epoch', async () => {
    server.maintenance.mockResolvedValue({ ...status('new-restore'), kind: 'restore', content_epoch: 'original', result: { success: true } });
    const gate = deferred<void>();
    invalidateOffline.mockReturnValueOnce(gate.promise);
    const pending = recoverPendingCenterMaintenance();
    await vi.waitFor(() => expect(invalidateOffline).toHaveBeenCalledOnce());
    expect(runtime.dataEpoch).toBe('original');
    expect(configure).not.toHaveBeenCalled();
    gate.resolve();
    await pending;
    expect(runtime.dataEpoch).toBe('new-restore');
    expect(cleanup).not.toHaveBeenCalled();
  });

  it('keeps the original scope and content when changed-epoch invalidation fails', async () => {
    centerLocalStorage().setItem('chat_session_active', 'old-session');
    server.maintenance.mockResolvedValue(status('missed-clear'));
    invalidateOffline.mockRejectedValueOnce(new Error('Native invalidation failed'));
    await expect(recoverPendingCenterMaintenance()).rejects.toThrow('Native invalidation failed');
    expect(centerLocalStorage().getItem('chat_session_active')).toBe('old-session');
    expect(runtime.contentEpoch).toBe('original');
    expect(cleanup).not.toHaveBeenCalled();
  });

  it.each(['existing', 'discovered'] as const)('invalidates before %s pending device cleanup without an epoch change', async (source) => {
    server.maintenance.mockResolvedValue(status('original'));
    if (source === 'existing') centerLocalStorage().setItem('maintenance.device-cleanup', 'pending');
    else window.localStorage.setItem('magi.center.center-a.previous.chat_session_active', 'old-session');
    const gate = deferred<void>();
    invalidateOffline.mockReturnValueOnce(gate.promise);
    const pending = recoverPendingCenterMaintenance();
    await vi.waitFor(() => expect(invalidateOffline).toHaveBeenCalledOnce());
    expect(cleanup).not.toHaveBeenCalled();
    expect(logs).not.toHaveBeenCalled();
    gate.resolve();
    await pending;
    expect(cleanup).toHaveBeenCalledOnce();
    expect(centerLocalStorage().getItem('maintenance.device-cleanup')).toBeNull();
  });

  it('does not invalidate unchanged idle observations', async () => {
    server.maintenance.mockResolvedValue(status('original'));
    await recoverPendingCenterMaintenance();
    await recoverPendingCenterMaintenance();
    expect(invalidateOffline).not.toHaveBeenCalled();
    expect(cleanup).not.toHaveBeenCalled();
  });

  it('does not admit maintenance after a connection switch while invalidation is pending', async () => {
    const gate = deferred<void>();
    invalidateOffline.mockReturnValueOnce(gate.promise);
    const pending = clearAllMemory();
    runtimeOwner.generation += 1;
    gate.resolve();
    await expect(pending).rejects.toThrow('Connection changed');
    expect(server.clear).not.toHaveBeenCalled();
    expect(centerLocalStorage().getItem('maintenance.pending-clear')).toBeNull();
  });

  it('ignores a maintenance response from a previous connection', async () => {
    const gate = deferred<ReturnType<typeof status>>();
    server.maintenance.mockReturnValueOnce(gate.promise);
    const pending = recoverPendingCenterMaintenance();
    runtimeOwner.generation += 1;
    gate.resolve(status('previous-center-clear'));
    await expect(pending).rejects.toThrow('Connection changed');
    expect(invalidateOffline).not.toHaveBeenCalled();
    expect(cleanup).not.toHaveBeenCalled();
    expect(runtime.contentEpoch).toBe('original');
  });

});
