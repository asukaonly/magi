import { beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryApi } from '@/api/modules/memory';
import { clearAllMemory, recoverPendingFullDataClear } from '@/hooks/clearAllMemory';
import { completeMemoryClear } from '@/hooks/chatRetryLifecycle';
import {
  beginFullDataClear,
  clearDesktopLogHistory,
  completeFullDataClear,
  readPendingFullDataClear,
} from '@/runtime/desktop';
import { APP_EVENTS } from '@/constants/events';
import { stopRuntimeForFullDataClearRecovery } from '@/runtime/config';

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    clearAll: vi.fn(),
  },
}));

vi.mock('@/hooks/chatRetryLifecycle', () => ({
  completeMemoryClear: vi.fn(),
}));

vi.mock('@/runtime/desktop', () => ({
  beginFullDataClear: vi.fn(),
  clearDesktopLogHistory: vi.fn(),
  completeFullDataClear: vi.fn(),
  readPendingFullDataClear: vi.fn(),
}));

vi.mock('@/runtime/config', () => ({
  stopRuntimeForFullDataClearRecovery: vi.fn(),
}));

describe('clearAllMemory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(completeMemoryClear).mockReturnValue({
      browserStateCleared: true,
      failedScopes: [],
    });
    vi.mocked(clearDesktopLogHistory).mockResolvedValue({
      clearedEntries: 4,
      failedEntries: 0,
    });
    vi.mocked(beginFullDataClear).mockResolvedValue({
      version: 1,
      transactionId: 'clear-transaction-1234',
    });
    vi.mocked(readPendingFullDataClear).mockResolvedValue(null);
    vi.mocked(completeFullDataClear).mockResolvedValue(undefined);
    vi.mocked(stopRuntimeForFullDataClearRecovery).mockResolvedValue(undefined);
  });

  it('acknowledges the desktop marker only after every clear step succeeds', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 1 },
        l1: { cleared: true, count: 2 },
        l2: { cleared: true, count: 3 },
        l3: { cleared: true, count: 4 },
        l4: { cleared: true, count: 5 },
        chat_context: { cleared: true, count: 6 },
      },
    });

    const result = await clearAllMemory();

    expect(result.warnings).toBeUndefined();
    expect(memoryApi.clearAll).toHaveBeenCalledWith('clear-transaction-1234');
    expect(clearDesktopLogHistory).toHaveBeenCalledOnce();
    expect(completeMemoryClear).toHaveBeenCalledOnce();
    expect(completeMemoryClear).toHaveBeenCalledWith(expect.objectContaining({
      announce: false,
    }));
    expect(completeFullDataClear).toHaveBeenCalledWith('clear-transaction-1234');
  });

  it('blocks the product when the desktop marker response is lost', async () => {
    const started = vi.fn();
    const failed = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, started);
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_FAILED, failed);
    vi.mocked(beginFullDataClear).mockRejectedValue(new Error('IPC response lost'));

    await expect(clearAllMemory()).rejects.toThrow('IPC response lost');

    expect(started).toHaveBeenCalledOnce();
    expect(stopRuntimeForFullDataClearRecovery).toHaveBeenCalledOnce();
    expect(failed).toHaveBeenCalledOnce();
    expect(memoryApi.clearAll).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, started);
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_FAILED, failed);
  });

  it('blocks the product when the desktop marker owner returns no result', async () => {
    const started = vi.fn();
    const failed = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, started);
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_FAILED, failed);
    vi.mocked(beginFullDataClear).mockResolvedValue(undefined);

    await expect(clearAllMemory()).rejects.toThrow(
      'Desktop full data clear owner is unavailable',
    );

    expect(started).toHaveBeenCalledOnce();
    expect(stopRuntimeForFullDataClearRecovery).toHaveBeenCalledOnce();
    expect(failed).toHaveBeenCalledOnce();
    expect(memoryApi.clearAll).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, started);
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_FAILED, failed);
  });

  it('keeps local retries when the clear boundary did not complete', async () => {
    const clearStarted = vi.fn();
    const clearCompleted = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, clearStarted);
    window.addEventListener(APP_EVENTS.MEMORY_CLEARED, clearCompleted);
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: false,
      results: {
        l0: { cleared: false, count: 0 },
        l1: { cleared: false, count: 0 },
        l2: { cleared: false, count: 0 },
        l3: { cleared: false, count: 0 },
        l4: { cleared: false, count: 0 },
        chat_context: { cleared: false, count: 0 },
      },
    });

    await expect(clearAllMemory()).rejects.toThrow(
      'Backend full data clear was not completed',
    );
    expect(completeMemoryClear).not.toHaveBeenCalled();
    expect(completeFullDataClear).not.toHaveBeenCalled();
    expect(stopRuntimeForFullDataClearRecovery).toHaveBeenCalledOnce();
    expect(clearStarted).toHaveBeenCalledTimes(1);
    expect(clearCompleted).not.toHaveBeenCalled();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, clearStarted);
    window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, clearCompleted);
  });

  it('keeps the transaction pending when desktop logs remain', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
    vi.mocked(clearDesktopLogHistory).mockResolvedValue({
      clearedEntries: 3,
      failedEntries: 1,
    });

    await expect(clearAllMemory()).rejects.toThrow(
      'Desktop diagnostic log clear was not completed',
    );

    expect(completeMemoryClear).toHaveBeenCalledOnce();
    expect(completeFullDataClear).not.toHaveBeenCalled();
  });

  it('replays the same clear after backend success when desktop log cleanup failed', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
    vi.mocked(clearDesktopLogHistory)
      .mockResolvedValueOnce({ clearedEntries: 3, failedEntries: 1 })
      .mockResolvedValueOnce({ clearedEntries: 1, failedEntries: 0 });

    await expect(clearAllMemory()).rejects.toThrow(
      'Desktop diagnostic log clear was not completed',
    );
    vi.mocked(readPendingFullDataClear).mockResolvedValue({
      version: 1,
      transactionId: 'clear-transaction-1234',
    });

    await expect(recoverPendingFullDataClear()).resolves.toBe(true);

    expect(memoryApi.clearAll).toHaveBeenCalledTimes(2);
    expect(memoryApi.clearAll).toHaveBeenNthCalledWith(1, 'clear-transaction-1234');
    expect(memoryApi.clearAll).toHaveBeenNthCalledWith(2, 'clear-transaction-1234');
    expect(completeFullDataClear).toHaveBeenCalledOnce();
    expect(completeFullDataClear).toHaveBeenCalledWith('clear-transaction-1234');
  });

  it('keeps the transaction pending when no desktop owner confirms log erasure', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
    vi.mocked(clearDesktopLogHistory).mockResolvedValue(undefined);

    await expect(clearAllMemory()).rejects.toThrow(
      'Desktop diagnostic log clear was not completed',
    );

    expect(completeMemoryClear).toHaveBeenCalledOnce();
    expect(completeFullDataClear).not.toHaveBeenCalled();
  });

  it('keeps the transaction pending when browser content remains', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
    vi.mocked(completeMemoryClear).mockReturnValue({
      browserStateCleared: false,
      failedScopes: ['onboarding'],
    });

    await expect(clearAllMemory()).rejects.toThrow(
      'Browser full data clear was not completed: onboarding',
    );

    expect(clearDesktopLogHistory).not.toHaveBeenCalled();
    expect(completeFullDataClear).not.toHaveBeenCalled();
  });

  it('treats backend residue warnings as an incomplete transaction', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      warnings: ['orchestration_cleanup_failed'],
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });

    await expect(clearAllMemory()).rejects.toThrow(
      'Backend full data clear was not completed',
    );
    expect(completeMemoryClear).not.toHaveBeenCalled();
    expect(completeFullDataClear).not.toHaveBeenCalled();
  });

  it('replays an existing desktop marker after restart and finally acknowledges it', async () => {
    vi.mocked(readPendingFullDataClear).mockResolvedValue({
      version: 1,
      transactionId: 'clear-recovered-transaction',
    });
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });

    await expect(recoverPendingFullDataClear()).resolves.toBe(true);

    expect(beginFullDataClear).not.toHaveBeenCalled();
    expect(memoryApi.clearAll).toHaveBeenCalledWith('clear-recovered-transaction');
    expect(completeFullDataClear).toHaveBeenCalledWith('clear-recovered-transaction');
  });

  it('does nothing during startup when there is no pending marker', async () => {
    await expect(recoverPendingFullDataClear()).resolves.toBe(false);
    expect(memoryApi.clearAll).not.toHaveBeenCalled();
    expect(completeMemoryClear).not.toHaveBeenCalled();
  });

  it('treats a non-desktop startup as having no pending marker', async () => {
    vi.mocked(readPendingFullDataClear).mockResolvedValue(undefined);

    await expect(recoverPendingFullDataClear()).resolves.toBe(false);

    expect(memoryApi.clearAll).not.toHaveBeenCalled();
    expect(stopRuntimeForFullDataClearRecovery).not.toHaveBeenCalled();
  });

  it('does not announce success when the final desktop acknowledgement fails', async () => {
    const completed = vi.fn();
    const failed = vi.fn();
    window.addEventListener(APP_EVENTS.MEMORY_CLEARED, completed);
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_FAILED, failed);
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
    vi.mocked(completeFullDataClear).mockRejectedValue(new Error('disk unavailable'));

    await expect(clearAllMemory()).rejects.toThrow('disk unavailable');
    expect(completed).not.toHaveBeenCalled();
    expect(stopRuntimeForFullDataClearRecovery).toHaveBeenCalledOnce();
    expect(failed).toHaveBeenCalledOnce();
    window.removeEventListener(APP_EVENTS.MEMORY_CLEARED, completed);
    window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_FAILED, failed);
  });
});
