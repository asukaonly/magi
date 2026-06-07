import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useProductTourFlag } from '@/hooks/useProductTourFlag';
import { configApi } from '@/api/modules/config';

describe('useProductTourFlag', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('reads completed=false then marks it true via GET→clone→PUT', async () => {
    vi.spyOn(configApi, 'get').mockResolvedValue({ data: { preferences: { product_tour_completed: false } } } as any);
    const update = vi.spyOn(configApi, 'update').mockResolvedValue({} as any);
    const { result } = renderHook(() => useProductTourFlag());
    await waitFor(() => expect(result.current.completed).toBe(false));
    await act(async () => { await result.current.markCompleted(); });
    expect(result.current.completed).toBe(true);
    await waitFor(() => expect(update).toHaveBeenCalled());
    const arg = (update.mock.calls[0][0] as any);
    expect(arg.preferences.product_tour_completed).toBe(true);
  });
});
