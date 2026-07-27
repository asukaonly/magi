import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryApi } from '@/api/modules/memory';
import { clearAllMemory } from '@/hooks/clearAllMemory';
import { useMemory } from '@/hooks/useMemory';

const { toastSuccessMock, toastWarningMock } = vi.hoisted(() => ({
  toastSuccessMock: vi.fn(),
  toastWarningMock: vi.fn(),
}));

vi.mock('@/hooks/clearAllMemory', () => ({
  clearAllMemory: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: toastSuccessMock,
    warning: toastWarningMock,
    error: vi.fn(),
  },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    getStatistics: vi.fn(),
    getL0Sessions: vi.fn(),
    getL1Events: vi.fn(),
    getL2Statistics: vi.fn(),
    getIdentityLinks: vi.fn(),
    getL2Relations: vi.fn(),
    getL2Assertions: vi.fn(),
    getL2Entities: vi.fn(),
    getL2Mentions: vi.fn(),
    getL2Snapshots: vi.fn(),
    getL2ConflictRules: vi.fn(),
    getL3Summaries: vi.fn(),
    getL4Skills: vi.fn(),
  },
}));

const emptyPage = { items: [], total: 0, limit: 50, offset: 0 };

describe('useMemory clear convergence', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(memoryApi.getStatistics).mockResolvedValue({
      l0: { active_sessions: 0, total_attention_items: 0 },
      l1: { event_count: 1 },
      l2: { relation_count: 0, assertion_count: 0 },
      l3: { summary_count: 0 },
      l4: { skill_count: 0, open_circuit_breakers: 0 },
    });
    vi.mocked(memoryApi.getL0Sessions).mockResolvedValue({
      ...emptyPage,
      stats: {
        active_sessions: 0,
        total_attention_items: 0,
      },
    });
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      items: [{
        event_id: 'event-before-clear',
        event_type: 'user_text',
        timestamp: 1,
        content: 'old memory',
        memory_domain: 'conversation',
        retention_class: 'standard',
        importance_score: 0.5,
        cognition_eligible: true,
      }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(memoryApi.getL2Statistics).mockResolvedValue({
      relation_count: 0,
      assertion_count: 0,
    });
    vi.mocked(memoryApi.getIdentityLinks).mockResolvedValue({
      canonical_self_id: 'self',
      links: [],
    });
    vi.mocked(memoryApi.getL2Relations).mockResolvedValue(emptyPage);
    vi.mocked(memoryApi.getL2Assertions).mockResolvedValue(emptyPage);
    vi.mocked(memoryApi.getL2Entities).mockResolvedValue(emptyPage);
    vi.mocked(memoryApi.getL2Mentions).mockResolvedValue(emptyPage);
    vi.mocked(memoryApi.getL2Snapshots).mockResolvedValue(emptyPage);
    vi.mocked(memoryApi.getL2ConflictRules).mockResolvedValue([]);
    vi.mocked(memoryApi.getL3Summaries).mockResolvedValue(emptyPage);
    vi.mocked(memoryApi.getL4Skills).mockResolvedValue(emptyPage);
    vi.mocked(clearAllMemory).mockResolvedValue({
      success: true,
      warnings: [],
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 1 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
  });

  it('drops stale rows and reports when post-clear refresh fails', async () => {
    const hook = renderHook(() => useMemory({ initialLoadScope: 'l1' }));
    await waitFor(() => expect(hook.result.current.l1Events).toHaveLength(1));
    vi.mocked(memoryApi.getL1Events).mockRejectedValueOnce(
      new Error('refresh failed'),
    );

    await act(async () => {
      await hook.result.current.handleClearConfirm();
    });

    expect(hook.result.current.l1Events).toEqual([]);
    expect(toastSuccessMock).toHaveBeenCalledWith(
      'memory.clearSuccess',
    );
    expect(toastWarningMock).toHaveBeenCalledWith(
      'memory.clearRefreshFailed',
    );
  });
});
