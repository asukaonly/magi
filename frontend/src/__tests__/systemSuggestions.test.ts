import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  unwrapGatewayPayload: <T,>(payload: { success?: boolean; data?: T } | T): T => {
    if (
      payload &&
      typeof payload === 'object' &&
      'success' in (payload as Record<string, unknown>) &&
      'data' in (payload as Record<string, unknown>)
    ) {
      return (payload as { data: T }).data;
    }
    return payload as T;
  },
}));

import { api } from '@/api/client';
import {
  checkSystemSuggestions,
  dismissSystemSuggestion,
  type SuggestionProposal,
} from '@/api/modules/systemSuggestions';

const mockedPost = vi.mocked(api.post);

describe('systemSuggestions client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('checkSystemSuggestions posts text + locale and returns suggestions array', async () => {
    mockedPost.mockResolvedValue({
      success: true,
      data: {
        suggestions: [
          {
            dedupe_key: 'browser_history',
            category: 'browser_history',
            plugins: [{
              plugin_id: 'chrome-history',
              name: 'Chrome History',
              name_i18n: {},
              icon: 'brand:googlechrome',
              installed: true,
            }],
            confidence: 0.85,
            rationale: { zh: '测试', en: 'test' },
          },
        ],
      },
    } as any);

    const result: SuggestionProposal[] = await checkSystemSuggestions({
      text: '我看了什么浏览',
      locale: 'zh',
    });

    expect(mockedPost).toHaveBeenCalledWith('/system-suggestions/check', {
      text: '我看了什么浏览',
      locale: 'zh',
      session_id: 'default',
    });
    expect(result).toHaveLength(1);
    expect(result[0].plugins[0].name).toBe('Chrome History');
  });

  it('checkSystemSuggestions threads sessionId into session_id', async () => {
    mockedPost.mockResolvedValue({
      success: true,
      data: { suggestions: [] },
    } as any);

    await checkSystemSuggestions({
      text: 'hi',
      locale: 'en',
      sessionId: 'sess-123',
    });

    expect(mockedPost).toHaveBeenCalledWith('/system-suggestions/check', {
      text: 'hi',
      locale: 'en',
      session_id: 'sess-123',
    });
  });

  it('dismissSystemSuggestion posts dedupe_key + kind', async () => {
    mockedPost.mockResolvedValue({
      success: true,
      data: { dedupe_key: 'browser_history', dismissed: true },
    } as any);

    const result = await dismissSystemSuggestion({
      dedupe_key: 'browser_history',
      kind: 'explicit',
    });

    expect(mockedPost).toHaveBeenCalledWith('/system-suggestions/dismiss', {
      dedupe_key: 'browser_history',
      kind: 'explicit',
    });
    expect(result.dismissed).toBe(true);
  });
});
