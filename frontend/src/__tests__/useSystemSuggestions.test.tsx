import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useSystemSuggestions } from '../hooks/useSystemSuggestions';
import { APP_EVENTS } from '../constants/events';

const mockCheck = vi.fn();
const mockDismiss = vi.fn();
vi.mock('../api/modules/systemSuggestions', () => ({
  checkSystemSuggestions: (args: any) => mockCheck(args),
  dismissSystemSuggestion: (args: any) => mockDismiss(args),
}));

describe('useSystemSuggestions', () => {
  beforeEach(() => {
    mockCheck.mockReset();
    mockDismiss.mockReset();
  });

  it('does not call check until triggerText is non-empty', () => {
    renderHook(() => useSystemSuggestions({ triggerText: '', locale: 'zh' }));
    expect(mockCheck).not.toHaveBeenCalled();
  });

  it('calls check when triggerText is set', async () => {
    mockCheck.mockResolvedValue([]);
    renderHook(() => useSystemSuggestions({ triggerText: 'hi', locale: 'zh' }));
    await waitFor(() =>
      expect(mockCheck).toHaveBeenCalledWith({ text: 'hi', locale: 'zh' }),
    );
  });

  it('re-checks suggestions when a PLUGINS_CHANGED app event fires', async () => {
    mockCheck.mockResolvedValue([]);
    renderHook(() => useSystemSuggestions({ triggerText: 'hi', locale: 'zh' }));
    await waitFor(() => expect(mockCheck).toHaveBeenCalledTimes(1));
    act(() => {
      window.dispatchEvent(new Event(APP_EVENTS.PLUGINS_CHANGED));
    });
    await waitFor(() => expect(mockCheck).toHaveBeenCalledTimes(2));
  });

  it('exposes the returned proposals', async () => {
    mockCheck.mockResolvedValue([
      {
        dedupe_key: 'browser_history',
        category: 'browser_history',
        plugins: [{ plugin_id: 'chrome-history', name: 'Chrome History', name_i18n: {}, icon: 'brand:googlechrome', installed: true }],
        confidence: 0.9,
        rationale: { zh: '测试', en: 'test' },
      },
    ]);
    const { result } = renderHook(() =>
      useSystemSuggestions({ triggerText: 'foo', locale: 'zh' }),
    );
    await waitFor(() => expect(result.current.proposals).toHaveLength(1));
    expect(result.current.proposals[0].category).toBe('browser_history');
  });

  it('dismiss removes the local entry and POSTs to the backend', async () => {
    mockCheck.mockResolvedValue([
      {
        dedupe_key: 'browser_history',
        category: 'browser_history',
        plugins: [{ plugin_id: 'chrome-history', name: 'Chrome History', name_i18n: {}, icon: 'brand:googlechrome', installed: true }],
        confidence: 0.9,
        rationale: { zh: '测试', en: 'test' },
      },
    ]);
    mockDismiss.mockResolvedValue({ dedupe_key: 'browser_history', dismissed: true });
    const { result } = renderHook(() =>
      useSystemSuggestions({ triggerText: 'foo', locale: 'zh' }),
    );
    await waitFor(() => expect(result.current.proposals).toHaveLength(1));
    await act(async () => {
      await result.current.dismiss('browser_history', 'explicit');
    });
    expect(mockDismiss).toHaveBeenCalledWith({
      dedupe_key: 'browser_history',
      kind: 'explicit',
    });
    expect(result.current.proposals).toHaveLength(0);
  });
});
