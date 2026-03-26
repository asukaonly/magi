import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { memoryApi } from '@/api/modules/memory';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    getStatistics: vi.fn(),
    getL0Sessions: vi.fn(),
    getL0Workbench: vi.fn(),
    getL1Events: vi.fn(),
    getL2Relations: vi.fn(),
    getL2Assertions: vi.fn(),
    getL2Statistics: vi.fn(),
    getIdentityLinks: vi.fn(),
    getL2Entities: vi.fn(),
    getL2Mentions: vi.fn(),
    getL2Snapshots: vi.fn(),
    getL2ConflictRules: vi.fn(),
    getL3Summaries: vi.fn(),
    getL4Skills: vi.fn(),
    search: vi.fn(),
    clearAll: vi.fn(),
    createManualL2Event: vi.fn(),
    replayL2Extraction: vi.fn(),
    flushL2Microbatches: vi.fn(),
    reconcileL2Entities: vi.fn(),
    refreshL2Snapshots: vi.fn(),
    upsertL2ConflictRule: vi.fn(),
  },
}));

describe('useMemory initial load scope', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(memoryApi.getStatistics).mockResolvedValue({
      l0: { active_sessions: 0, total_goals: 0, total_entities: 0, total_tactics: 0 },
      l1: { event_count: 0 },
      l2: { relation_count: 0, assertion_count: 0 },
      l3: { summary_count: 0 },
      l4: { skill_count: 0, open_circuit_breakers: 0 },
    });
    vi.mocked(memoryApi.getL0Sessions).mockResolvedValue({
      sessions: [],
      stats: { active_sessions: 0, total_goals: 0, total_entities: 0, total_tactics: 0 },
    });
    vi.mocked(memoryApi.getL0Workbench).mockResolvedValue({
      session: null,
      goal_stack: [],
      active_entities: [],
      temporary_tactics: [],
    });
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({ events: [], stats: { total: 0 } });
    vi.mocked(memoryApi.getL2Relations).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Assertions).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Statistics).mockResolvedValue({
      canonical_self_id: 'user:self',
      identity_link_count: 0,
      relation_count: 0,
      assertion_count: 0,
      extract_skipped: 0,
      extract_by_evidence_class: {},
      skip_by_reason: {},
    });
    vi.mocked(memoryApi.getIdentityLinks).mockResolvedValue({
      canonical_self_id: 'user:self',
      links: [],
    });
    vi.mocked(memoryApi.getL2Entities).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Mentions).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Snapshots).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2ConflictRules).mockResolvedValue([]);
    vi.mocked(memoryApi.getL3Summaries).mockResolvedValue([]);
    vi.mocked(memoryApi.getL4Skills).mockResolvedValue([]);
    vi.mocked(memoryApi.search).mockResolvedValue({
      l0_workbench: [],
      l1_events: [],
      l2_entity_cards: [],
      l2_relationships: [],
      l3_reflections: [],
      l4_procedures: [],
      trace: {},
    });
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 0 },
        l1: { cleared: true, count: 0 },
        l2: { cleared: true, count: 0 },
        l3: { cleared: true, count: 0 },
        l4: { cleared: true, count: 0 },
        chat_context: { cleared: true, count: 0 },
      },
    });
    vi.mocked(memoryApi.flushL2Microbatches).mockResolvedValue({
      queued: true,
      batch_count: 2,
    } as any);
  });

  it('only loads statistics during overview initialization', async () => {
    renderHook(() => useMemory({ initialLoadScope: 'overview' }));

    await waitFor(() => {
      expect(memoryApi.getStatistics).toHaveBeenCalledTimes(1);
    });

    expect(memoryApi.getL0Sessions).not.toHaveBeenCalled();
    expect(memoryApi.getL1Events).not.toHaveBeenCalled();
    expect(memoryApi.getL2Statistics).not.toHaveBeenCalled();
    expect(memoryApi.getL3Summaries).not.toHaveBeenCalled();
    expect(memoryApi.getL4Skills).not.toHaveBeenCalled();
  });

  it('loads only knowledge-page dependencies for l2 initialization', async () => {
    renderHook(() => useMemory({ initialLoadScope: 'l2' }));

    await waitFor(() => {
      expect(memoryApi.getStatistics).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL1Events).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2Statistics).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2Relations).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2Assertions).toHaveBeenCalledTimes(1);
      expect(memoryApi.getIdentityLinks).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2Entities).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2Mentions).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2Snapshots).toHaveBeenCalledTimes(1);
      expect(memoryApi.getL2ConflictRules).toHaveBeenCalledTimes(1);
    });

    expect(memoryApi.getL0Sessions).not.toHaveBeenCalled();
    expect(memoryApi.getL3Summaries).not.toHaveBeenCalled();
    expect(memoryApi.getL4Skills).not.toHaveBeenCalled();
  });

  it('flushes pending L2 microbatches and refreshes knowledge data', async () => {
    const { result } = renderHook(() => useMemory({ initialLoadScope: 'l2' }));

    await waitFor(() => {
      expect(memoryApi.getL2Statistics).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      await result.current.flushL2Microbatches();
    });

    expect(memoryApi.flushL2Microbatches).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(memoryApi.getStatistics).toHaveBeenCalledTimes(2);
      expect(memoryApi.getL1Events).toHaveBeenCalledTimes(2);
      expect(memoryApi.getL2Statistics).toHaveBeenCalledTimes(2);
    });
  });
});
