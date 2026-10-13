import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryApi, type L2Entity, type L2Relation, type PaginatedResponse } from '@/api/modules/memory';
import { useMemoryKnowledge } from '@/hooks/useMemoryKnowledge';

vi.mock('@/api/modules/memory', () => ({ memoryApi: {
  getL2Relations: vi.fn(), getL2Assertions: vi.fn(), getL2Entities: vi.fn(),
} }));

const empty = { items: [], total: 0, limit: 50, offset: 0 };
const relation = (id: string): L2Relation => ({
  triple_id: id, subject_id: 'user:self', subject_type: 'person', predicate: 'LIVES_IN',
  object_id: 'place:old', object_type: 'place', confidence: 0.9, evidence_event_ids: [],
  observation_count: 1, first_observed_at: 1, last_observed_at: 1, status: 'active',
});
const entity = (id: string): L2Entity => ({ entity_id: id, canonical_name: id, entity_type: 'place', aliases: [] });

describe('useMemoryKnowledge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(memoryApi.getL2Relations).mockResolvedValue(empty);
    vi.mocked(memoryApi.getL2Assertions).mockResolvedValue(empty);
    vi.mocked(memoryApi.getL2Entities).mockResolvedValue(empty);
  });

  it('applies global query and filters before separately paging every record kind', async () => {
    vi.mocked(memoryApi.getL2Relations).mockResolvedValueOnce({ ...empty, items: Array.from({ length: 50 }, (_, i) => relation(String(i))), total: 51 });
    vi.mocked(memoryApi.getL2Entities).mockResolvedValueOnce({ ...empty, items: Array.from({ length: 50 }, (_, i) => entity(String(i))), total: 51 });
    const { result } = renderHook(() => useMemoryKnowledge('京都', 'deprecated', 'place', true));
    await waitFor(() => expect(result.current.relations.total).toBe(51));
    expect(memoryApi.getL2Relations).toHaveBeenCalledWith({ query: '京都', status_group: 'deprecated', entity_type: 'place', include_inactive: true, limit: 50, offset: 0 });
    expect(memoryApi.getL2Assertions).toHaveBeenCalledWith({ query: '京都', status_group: 'deprecated', entity_type: 'place', include_inactive: true, limit: 50, offset: 0 });
    expect(memoryApi.getL2Entities).toHaveBeenCalledWith({ query: '京都', entity_type: 'place', limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL2Relations).mockResolvedValueOnce({ ...empty, items: [relation('older')], total: 51, offset: 50 });
    vi.mocked(memoryApi.getL2Entities).mockResolvedValueOnce({ ...empty, items: [entity('older')], total: 51, offset: 50 });
    await act(async () => { await Promise.all([result.current.relations.loadMore(), result.current.entities.loadMore()]); });
    expect(result.current.relations.items.at(-1)?.triple_id).toBe('older');
    expect(result.current.entities.items.at(-1)?.entity_id).toBe('older');
    expect(memoryApi.getL2Relations).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50, limit: 50 }));
    expect(memoryApi.getL2Entities).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50, limit: 50 }));
  });

  it('never displays an older in-flight query after the filters change', async () => {
    let finishOld!: (page: PaginatedResponse<L2Relation>) => void;
    vi.mocked(memoryApi.getL2Relations).mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; }));
    const { result, rerender } = renderHook(({ query }) => useMemoryKnowledge(query, undefined, undefined, true), { initialProps: { query: 'old' } });
    vi.mocked(memoryApi.getL2Relations).mockResolvedValueOnce({ ...empty, items: [relation('new')], total: 1 });
    rerender({ query: 'new' });
    await waitFor(() => expect(result.current.relations.items[0]?.triple_id).toBe('new'));
    await act(async () => { finishOld({ ...empty, items: [relation('old')], total: 1 }); });
    expect(result.current.relations.items.map(row => row.triple_id)).toEqual(['new']);
  });

  it('retains loaded pages on append failure and retries the same bounded offset', async () => {
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(memoryApi.getL2Relations).mockResolvedValueOnce({ ...empty, items: [relation('first')], total: 2 });
    const { result } = renderHook(() => useMemoryKnowledge('', undefined, undefined, true));
    await waitFor(() => expect(result.current.relations.total).toBe(2));
    vi.mocked(memoryApi.getL2Relations).mockRejectedValueOnce(new Error('offline'));
    await act(async () => { await result.current.relations.loadMore(); });
    expect(result.current.relations.error).toBe(true);
    expect(result.current.relations.items.map(row => row.triple_id)).toEqual(['first']);
    vi.mocked(memoryApi.getL2Relations).mockResolvedValueOnce({ ...empty, items: [relation('second')], total: 2, offset: 1 });
    await act(async () => { await result.current.relations.retry(); });
    expect(memoryApi.getL2Relations).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 1 }));
    expect(result.current.relations.error).toBe(false);
    expect(result.current.relations.items.map(row => row.triple_id)).toEqual(['first', 'second']);
    errorLog.mockRestore();
  });

  it('reports first-page failure without claiming that zero records exist', async () => {
    const errorLog = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(memoryApi.getL2Assertions).mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useMemoryKnowledge('', undefined, undefined, true));
    await waitFor(() => expect(result.current.assertions.error).toBe(true));
    expect(result.current.assertions.total).toBeNull();
    await act(async () => { await result.current.assertions.retry(); });
    expect(result.current.assertions.total).toBe(0);
    expect(result.current.assertions.error).toBe(false);
    errorLog.mockRestore();
  });
});
