import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { dispatchAppEvent } from '@/constants/events';
import { useMemoryClearEpoch } from '@/hooks/useMemoryClearEpoch';

describe('useMemoryClearEpoch', () => {
  it('changes only after a completed memory clear', () => {
    const { result } = renderHook(() => useMemoryClearEpoch());
    expect(result.current).toBe(0);

    act(() => dispatchAppEvent.memoryCleared());

    expect(result.current).toBe(1);
  });
});
