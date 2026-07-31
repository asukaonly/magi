import { beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryApi } from '@/api/modules/memory';
import { clearAllMemory } from '@/hooks/clearAllMemory';
import { completeMemoryClear } from '@/hooks/chatRetryLifecycle';
import { clearDesktopLogHistory } from '@/runtime/desktop';

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    clearAll: vi.fn(),
  },
}));

vi.mock('@/hooks/chatRetryLifecycle', () => ({
  completeMemoryClear: vi.fn(),
}));

vi.mock('@/runtime/desktop', () => ({
  clearDesktopLogHistory: vi.fn(),
}));

describe('clearAllMemory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(clearDesktopLogHistory).mockResolvedValue({
      clearedEntries: 4,
      failedEntries: 0,
    });
  });

  it('drops local retries when data cleared with recovery warnings', async () => {
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      warnings: ['orchestration_cleanup_failed'],
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

    expect(result.warnings).toEqual(['orchestration_cleanup_failed']);
    expect(clearDesktopLogHistory).toHaveBeenCalledOnce();
    expect(completeMemoryClear).toHaveBeenCalledOnce();
  });

  it('keeps local retries when the clear boundary did not complete', async () => {
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
      'Memory clear request was not completed',
    );
    expect(completeMemoryClear).not.toHaveBeenCalled();
  });

  it('keeps the data clear successful but warns when desktop logs remain', async () => {
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

    const result = await clearAllMemory();

    expect(result.warnings).toEqual(['diagnostic_log_cleanup_failed']);
    expect(completeMemoryClear).toHaveBeenCalledOnce();
  });

  it('warns when no desktop owner confirms that host logs were erased', async () => {
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

    const result = await clearAllMemory();

    expect(result.warnings).toEqual(['diagnostic_log_cleanup_failed']);
    expect(completeMemoryClear).toHaveBeenCalledOnce();
  });
});
