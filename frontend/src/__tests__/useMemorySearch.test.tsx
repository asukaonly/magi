import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { memoryApi, type MemorySearchResultPayload } from '@/api/modules/memory';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/api/modules/memory', () => ({ memoryApi: { search: vi.fn(), getStatistics: vi.fn() } }));

const empty: MemorySearchResultPayload = {
  l0_workbench: [], l1_events: [], l2_entity_cards: [], l2_relationships: [],
  l3_reflections: [], l4_procedures: [], trace: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryApi.getStatistics).mockResolvedValue({
    l0: { active_sessions: 0, total_attention_items: 0 }, l1: { event_count: 0 },
    l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 },
    l4: { skill_count: 0, open_circuit_breakers: 0 },
  });
});

it('distinguishes failure from a successful empty result and permits retry', async () => {
  vi.mocked(memoryApi.search).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce(empty);
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.setSearchQuery('apricot'));
  await act(() => result.current.handleSearch());
  expect(result.current.searchError).toBe(true);
  expect(result.current.searching).toBe(false);
  await act(() => result.current.handleSearch());
  expect(result.current.searchError).toBe(false);
  expect(result.current.searchResults).toEqual(empty);
});

it('deduplicates submissions and ignores responses after the query changes or the view closes', async () => {
  let resolveOld!: (value: MemorySearchResultPayload) => void;
  let rejectNew!: (error: Error) => void;
  vi.mocked(memoryApi.search).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectNew = reject; }));
  const { result, unmount } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.setSearchQuery('old'));
  let pending!: Promise<void>;
  act(() => { pending = result.current.handleSearch(); });
  await act(() => result.current.handleSearch());
  expect(memoryApi.search).toHaveBeenCalledTimes(1);
  act(() => result.current.setSearchQuery('new'));
  await act(async () => { resolveOld({ ...empty, l1_events: [{ title: 'Old result' }] }); await pending; });
  expect(result.current.searchResults.l1_events).toEqual([]);
  act(() => { pending = result.current.handleSearch(); });
  unmount();
  await act(async () => { rejectNew(new Error('Late failure')); await pending; });
});
