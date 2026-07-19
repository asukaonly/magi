import { describe, expect, it } from 'vitest';

import type { ClearMemoryResponse } from '@/api/modules/memory';
import { summarizeMemoryClear } from '@/hooks/memoryClearFeedback';

const clearResult = (
  overrides: Partial<ClearMemoryResponse> = {},
): ClearMemoryResponse => ({
  success: true,
  results: {
    l0: { cleared: true, count: 1 },
    l1: { cleared: true, count: 2 },
    l2: { cleared: true, count: 3 },
    l3: { cleared: true, count: 4 },
    l4: { cleared: true, count: 5 },
    chat_context: { cleared: true, count: 6 },
  },
  warnings: [],
  ...overrides,
});

describe('summarizeMemoryClear', () => {
  it('counts every cleared memory and conversation item', () => {
    expect(summarizeMemoryClear(clearResult())).toEqual({
      clearedItemCount: 21,
      recoveryPending: false,
      otherWarningsPresent: false,
    });
  });

  it('reports background recovery without counting uncleared rows', () => {
    const result = clearResult({
      results: {
        ...clearResult().results,
        l4: { cleared: false, count: 5 },
      },
      warnings: ['channel_conversation_cleanup_pending'],
    });

    expect(summarizeMemoryClear(result)).toEqual({
      clearedItemCount: 16,
      recoveryPending: true,
      otherWarningsPresent: false,
    });
  });

  it('does not describe a non-blocking warning as paused conversation recovery', () => {
    expect(summarizeMemoryClear(clearResult({
      warnings: ['sensor_cleanup_failed'],
    }))).toEqual({
      clearedItemCount: 21,
      recoveryPending: false,
      otherWarningsPresent: true,
    });
  });
});
