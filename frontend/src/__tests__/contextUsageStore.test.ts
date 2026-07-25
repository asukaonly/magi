import { beforeEach, describe, expect, it } from 'vitest';
import { useContextUsageStore } from '@/stores/context-usage';

describe('context usage store', () => {
  beforeEach(() => {
    useContextUsageStore.getState().reset();
  });

  it('keeps the newest durable snapshot when a delayed event arrives', () => {
    useContextUsageStore.getState().update('session-1', {
      turn_id: 'turn-2',
      used_tokens: 6_064,
      window_size: 1_000_000,
      input_capacity: 983_616,
      threshold: 491_808,
      measurement: 'actual',
      updated_at_ms: 2_000,
    });
    useContextUsageStore.getState().update('session-1', {
      turn_id: 'turn-1',
      used_tokens: 2_633,
      window_size: 256_000,
      threshold: 192_000,
      measurement: 'actual',
      updated_at_ms: 1_000,
    });

    expect(useContextUsageStore.getState().usage['session-1']).toMatchObject({
      turnId: 'turn-2',
      usedTokens: 6_064,
      windowSize: 1_000_000,
      inputCapacity: 983_616,
      updatedAt: 2_000,
    });
  });

  it('does not turn a missing measurement into a zero snapshot', () => {
    useContextUsageStore.getState().update('session-1', {
      used_tokens: 0,
      window_size: 1_000_000,
      threshold: 500_000,
    });

    expect(useContextUsageStore.getState().usage['session-1']).toBeUndefined();
  });
});
