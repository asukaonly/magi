import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { memoryApi, type MemoryListQueryParams, type PaginatedResponse } from '@/api/modules/memory';
import { useCenterRefresh } from './useCenterRefresh';
import { useRequestOwner } from './useRequestOwner';

const PAGE_SIZE = 50;

export interface KnowledgePageState<T> {
  items: T[];
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
  error: boolean;
  loadMore: () => Promise<void>;
  retry: () => Promise<void>;
  reload: () => Promise<void>;
}

function useKnowledgeRecords<T>(
  fetchPage: (params: MemoryListQueryParams) => Promise<PaginatedResponse<T>>,
  params: MemoryListQueryParams,
  enabled: boolean,
): KnowledgePageState<T> {
  const scope = JSON.stringify([enabled, params]);
  const beginRequest = useRequestOwner(scope);
  const [state, setState] = useState({
    scope, items: [] as T[], total: null as number | null,
    loading: enabled, loadingMore: false, error: false, nextOffset: 0,
  });
  const stateRef = useRef(state);
  stateRef.current = state;
  const load = useCallback(async (append = false) => {
    if (!enabled) return;
    const isCurrent = beginRequest('page');
    if (!isCurrent()) return;
    const offset = append && stateRef.current.scope === scope ? stateRef.current.nextOffset : 0;
    setState(current => ({
      ...current, scope, error: false, loading: !append, loadingMore: append,
      ...(!append ? { items: [], total: null, nextOffset: 0 } : {}),
    }));
    try {
      const page = await fetchPage({ ...params, limit: PAGE_SIZE, offset });
      if (!isCurrent()) return;
      if (page.items.length === 0 && page.total > offset) throw new Error('Knowledge page did not advance');
      setState(current => ({
        scope,
        items: append ? [...current.items, ...page.items] : page.items,
        total: page.total,
        nextOffset: offset + page.items.length,
        loading: false, loadingMore: false, error: false,
      }));
    } catch (error) {
      if (!isCurrent()) return;
      console.error('Failed to load knowledge records:', error);
      setState(current => ({ ...current, loading: false, loadingMore: false, error: true }));
    }
  }, [beginRequest, enabled, fetchPage, params, scope]);

  useEffect(() => { void load(); }, [load]);
  useCenterRefresh(() => load(), ['memory'], enabled);
  const loadMore = useCallback(async () => {
    const current = stateRef.current;
    if (current.loading || current.loadingMore || current.total === null || current.nextOffset >= current.total) return;
    await load(true);
  }, [load]);
  const retry = useCallback(() => load(stateRef.current.nextOffset > 0), [load]);
  const reload = useCallback(() => load(), [load]);
  if (state.scope !== scope) {
    return { items: [], total: null, loading: enabled, loadingMore: false, error: false, loadMore, retry, reload };
  }
  return { ...state, loadMore, retry, reload };
}

export function useMemoryKnowledge(
  query: string,
  statusGroup: MemoryListQueryParams['status_group'],
  entityType: string | undefined,
  enabled: boolean,
) {
  const factParams = useMemo(() => ({
    query: query.trim() || undefined,
    status_group: statusGroup,
    entity_type: entityType,
    include_inactive: true,
  }), [entityType, query, statusGroup]);
  const entityParams = useMemo(() => ({ query: query.trim() || undefined, entity_type: entityType }), [entityType, query]);
  const relations = useKnowledgeRecords(memoryApi.getL2Relations, factParams, enabled);
  const assertions = useKnowledgeRecords(memoryApi.getL2Assertions, factParams, enabled);
  const entities = useKnowledgeRecords(memoryApi.getL2Entities, entityParams, enabled);
  return { relations, assertions, entities };
}

export type MemoryKnowledgePages = ReturnType<typeof useMemoryKnowledge>;
