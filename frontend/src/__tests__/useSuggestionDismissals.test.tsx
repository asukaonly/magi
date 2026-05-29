import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useSuggestionDismissals } from '@/hooks/useSuggestionDismissals';
import * as api from '@/api/modules/systemSuggestions';

describe('useSuggestionDismissals', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'listDismissals').mockResolvedValue([
      { dedupe_key: 'browser_history', dismissed_at: 'x', kind: 'explicit' },
      { dedupe_key: 'calendar', dismissed_at: 'x', kind: 'never' },
    ]);
    vi.spyOn(api, 'clearDismissal').mockResolvedValue();
  });

  it('exposes items and a non-permanent count', async () => {
    const { result } = renderHook(() => useSuggestionDismissals());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.activeCount).toBe(1); // excludes kind=never
  });

  it('clears one and refetches', async () => {
    const { result } = renderHook(() => useSuggestionDismissals());
    await waitFor(() => expect(result.current.items.length).toBe(2));
    await act(async () => { await result.current.clear('browser_history'); });
    expect(api.clearDismissal).toHaveBeenCalledWith('browser_history');
  });
});
