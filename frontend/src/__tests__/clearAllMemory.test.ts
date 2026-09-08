import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const { runtime, server, cleanup, logs, configure } = vi.hoisted(() => ({
  runtime: { serverId: 'center-a', dataEpoch: 'original', apiBaseUrl: 'https://center.example/api', sessionToken: 'token' },
  server: { clear: vi.fn(), maintenance: vi.fn() }, cleanup: vi.fn(), logs: vi.fn(), configure: vi.fn(),
}));
vi.mock('@/api/modules/server', () => ({ serverApi: server }));
vi.mock('@/api/client', () => ({ configureApiClient: configure }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => runtime, getRuntimeGeneration: () => 1, assertRuntimeGeneration: vi.fn(), setRuntimeDataEpoch: (epoch: string) => { runtime.dataEpoch = epoch; } }));
vi.mock('@/runtime/desktop', () => ({ clearDesktopLogHistory: logs }));
vi.mock('@/hooks/chatRetryLifecycle', () => ({ completeMemoryClear: cleanup }));
import { clearAllMemory, recoverPendingFullDataClear } from '@/hooks/clearAllMemory';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import { APP_EVENTS } from '@/constants/events';
const results = Object.fromEntries(['l0', 'l1', 'l2', 'l3', 'l4', 'chat_context'].map((area) => [area, { cleared: true, count: 2 }]));
const receipt = { success: true, results, warnings: [] };
const status = (operationId: string, phase = 'completed') => ({ version: 1, operation_id: operationId, phase, data_epoch: phase === 'completed' ? operationId : 'original', result: phase === 'completed' ? receipt : null, error: phase === 'failed' ? 'Worker failed' : null });

describe('center-owned full clear', () => {
  beforeEach(() => {
    vi.clearAllMocks(); window.localStorage.clear(); window.sessionStorage.clear(); runtime.dataEpoch = 'original';
    setCenterStorageScope(runtime.serverId, 'original');
    cleanup.mockReturnValue({ browserStateCleared: true, failedScopes: [] });
    logs.mockResolvedValue({ clearedEntries: 1, failedEntries: 0 });
    server.clear.mockImplementation(async (id: string) => status(id));
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
    const pending = recoverPendingFullDataClear(); await vi.runAllTimersAsync();
    await expect(pending).resolves.toBe(true); expect(server.clear).not.toHaveBeenCalled();
  });
  it('does not resubmit a failed center operation without an explicit retry', async () => {
    server.maintenance.mockResolvedValue(status('remote-operation', 'failed'));
    await expect(recoverPendingFullDataClear()).rejects.toThrow('Worker failed'); expect(server.clear).not.toHaveBeenCalled();
    await expect(recoverPendingFullDataClear(true)).resolves.toBe(true); expect(server.clear).toHaveBeenCalledWith('remote-operation');
  });
  it('keeps device cleanup pending if diagnostic log cleanup fails, without rerunning center deletion', async () => {
    logs.mockResolvedValueOnce({ clearedEntries: 0, failedEntries: 1 });
    await expect(clearAllMemory()).rejects.toThrow('diagnostic logs');
    expect(centerLocalStorage().getItem('maintenance.device-cleanup')).toBe('pending');
    server.maintenance.mockResolvedValue(status(runtime.dataEpoch));
    await recoverPendingFullDataClear(); expect(server.clear).toHaveBeenCalledOnce(); expect(logs).toHaveBeenCalledTimes(2);
    expect(centerLocalStorage().getItem('maintenance.device-cleanup')).toBeNull();
  });
  it('rejects incomplete center receipts before releasing the product gate', async () => {
    const released = vi.fn(); window.addEventListener(APP_EVENTS.MEMORY_CLEARED, released);
    server.clear.mockImplementation(async (id: string) => ({ ...status(id), result: { ...receipt, results: { ...results, l0: { cleared: false, count: 0 } } } }));
    await expect(clearAllMemory()).rejects.toThrow(); expect(cleanup).not.toHaveBeenCalled(); expect(released).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, released);
  });
});
