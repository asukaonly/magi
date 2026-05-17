import { renderHook, waitFor, act } from '@testing-library/react';
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { useMemoryPortrait } from '@/hooks/useMemoryPortrait';
import { memoryPortraitApi } from '@/api/modules/memoryPortrait';

vi.mock('@/api/modules/memoryPortrait', () => ({
  memoryPortraitApi: {
    get: vi.fn(),
  },
}));

describe('useMemoryPortrait', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(memoryPortraitApi.get).mockReset().mockResolvedValue({
      session_id: 's1',
      persona_id: 'p1',
      topic: 't',
      generated_at: 0,
      observations: [],
      is_cold_start: true,
      cold_start_line: 'hi',
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fetches on mount with session and user', async () => {
    renderHook(() => useMemoryPortrait({ sessionId: 's1', userId: 'u1', personaId: 'p1' }));
    await waitFor(() => {
      expect(memoryPortraitApi.get).toHaveBeenCalledWith('s1', 'u1', { force: false });
    });
  });

  it('refetches with force=true when persona changes', async () => {
    const { rerender } = renderHook(
      ({ personaId }) => useMemoryPortrait({ sessionId: 's1', userId: 'u1', personaId }),
      { initialProps: { personaId: 'p1' } },
    );
    await waitFor(() => expect(memoryPortraitApi.get).toHaveBeenCalledTimes(1));
    rerender({ personaId: 'p2' });
    await waitFor(() => {
      expect(memoryPortraitApi.get).toHaveBeenLastCalledWith('s1', 'u1', { force: true });
    });
  });

  it('throttles refresh within 5 minutes', async () => {
    const { result } = renderHook(() =>
      useMemoryPortrait({ sessionId: 's1', userId: 'u1', personaId: 'p1' }),
    );
    await waitFor(() => expect(memoryPortraitApi.get).toHaveBeenCalledTimes(1));
    act(() => {
      result.current.refresh();
    });
    expect(memoryPortraitApi.get).toHaveBeenCalledTimes(1);
    act(() => {
      vi.advanceTimersByTime(5 * 60 * 1000 + 1);
    });
    act(() => {
      result.current.refresh();
    });
    await waitFor(() => expect(memoryPortraitApi.get).toHaveBeenCalledTimes(2));
  });

  it('returns null payload when sessionId is empty', () => {
    const { result } = renderHook(() =>
      useMemoryPortrait({ sessionId: '', userId: 'u1', personaId: 'p1' }),
    );
    expect(result.current.payload).toBeNull();
    expect(memoryPortraitApi.get).not.toHaveBeenCalled();
  });
});
