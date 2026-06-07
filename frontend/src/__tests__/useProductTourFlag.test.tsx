import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useProductTourFlag } from '@/hooks/useProductTourFlag';
import { useProductTourStore } from '@/stores/productTour';
import { configApi } from '@/api/modules/config';

describe('useProductTourFlag', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Reset the shared store between tests (it's a module singleton).
    useProductTourStore.setState({ completed: true, loaded: false });
  });

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

  it('shares state across consumers: marking in one instance flips the other (regression: deferred opening must fire)', async () => {
    vi.spyOn(configApi, 'get').mockResolvedValue({ data: { preferences: { product_tour_completed: false } } } as any);
    vi.spyOn(configApi, 'update').mockResolvedValue({} as any);
    // Two independent consumers (e.g. MainLayout + useChatSessionLifecycle).
    const a = renderHook(() => useProductTourFlag());
    const b = renderHook(() => useProductTourFlag());
    await waitFor(() => expect(a.result.current.completed).toBe(false));
    await waitFor(() => expect(b.result.current.completed).toBe(false));
    // Complete via consumer A...
    await act(async () => { await a.result.current.markCompleted(); });
    // ...consumer B must observe it (shared store), otherwise the deferred
    // bootstrap opening in useChatSessionLifecycle would never fire.
    expect(b.result.current.completed).toBe(true);
  });
});
