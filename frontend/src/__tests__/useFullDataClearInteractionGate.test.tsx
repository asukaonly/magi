import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { dispatchAppEvent } from '@/constants/events';
import { useFullDataClearInteractionGate } from '@/hooks/useFullDataClearInteractionGate';

describe('full data clear interaction gate', () => {
  it('blocks normal interaction until the transaction announces completion', () => {
    const { result } = renderHook(() => useFullDataClearInteractionGate());

    expect(result.current.gate.status).toBe('idle');

    act(() => dispatchAppEvent.memoryClearStarted());
    expect(result.current.gate.status).toBe('running');

    act(() => dispatchAppEvent.memoryClearFailed('desktop marker remains pending'));
    expect(result.current.gate).toEqual({
      status: 'failed',
      message: 'desktop marker remains pending',
    });

    act(() => result.current.markRetrying());
    expect(result.current.gate.status).toBe('running');

    act(() => dispatchAppEvent.memoryClearRecoveryReleased());
    expect(result.current.gate.status).toBe('idle');
  });
});
