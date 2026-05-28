import { renderHook, act, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useFirstConversationFlag } from '../hooks/useFirstConversationFlag';

const mockGet = vi.fn();
const mockUpdate = vi.fn();
vi.mock('../api/modules/config', () => ({
  configApi: {
    get: () => mockGet(),
    update: (cfg: any) => mockUpdate(cfg),
  },
}));

describe('useFirstConversationFlag', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockUpdate.mockReset();
  });

  it('returns false initially while config loads', () => {
    mockGet.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useFirstConversationFlag());
    expect(result.current.completed).toBe(false);
    expect(result.current.loading).toBe(true);
  });

  it('returns true when preferences.first_conversation_completed === true', async () => {
    mockGet.mockResolvedValue({
      preferences: { first_conversation_completed: true },
    });
    const { result } = renderHook(() => useFirstConversationFlag());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.completed).toBe(true);
  });

  it('returns false when preferences are missing the field', async () => {
    mockGet.mockResolvedValue({ preferences: {} });
    const { result } = renderHook(() => useFirstConversationFlag());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.completed).toBe(false);
  });

  it('markCompleted reads current config then PUTs the full body with the flag set', async () => {
    const fullCurrentConfig = {
      preferences: { first_conversation_completed: false, language: 'en' },
      llm: { providers: { foo: { enabled: true } } },
    };
    mockGet.mockResolvedValue(fullCurrentConfig);
    mockUpdate.mockResolvedValue({});
    const { result } = renderHook(() => useFirstConversationFlag());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.markCompleted();
    });
    // The PUT body must contain BOTH the new flag AND the prior fields
    // (proving it's a full body, not a partial one).
    expect(mockUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        preferences: expect.objectContaining({
          first_conversation_completed: true,
          language: 'en', // preserved!
        }),
        llm: expect.objectContaining({
          providers: expect.objectContaining({ foo: { enabled: true } }),
        }),
      }),
    );
    expect(result.current.completed).toBe(true);
  });
});
