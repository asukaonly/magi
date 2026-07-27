/**
 * useMemory hook - Manages memory system state and operations.
 *
 * This hook encapsulates all memory-related business logic including:
 * - Loading memory statistics and data for each layer (L0-L4)
 * - Session selection and workbench loading
 * - Search functionality
 * - Clear memory operations
 */

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { memoryApi } from '@/api/modules/memory';
import { clearAllMemory } from './clearAllMemory';
import { summarizeMemoryClear } from './memoryClearFeedback';
import type {
  L0Session,
  L0Workbench,
  L1Event,
  L1EventQueryParams,
  L2Relation,
  L2Assertion,
  L2Entity,
  L2GraphConflictRule,
  L2GraphConflictRulePayload,
  MemoryIdentityLink,
  L2Statistics,
  L2Mention,
  L2Snapshot,
  ManualL2EventPayload,
  L3Summary,
  L4Skill,
  MemoryStatistics,
  MemorySearchResultPayload,
  MemorySearchQueryMode,
  MemoryListQueryParams,
  PaginationParams,
} from '@/api/modules/memory';

// ============================================================================
// Types
// ============================================================================

export interface UseMemoryReturn {
  // Loading state
  loading: boolean;

  // Statistics
  stats: MemoryStatistics;

  // L0 data
  l0Sessions: L0Session[];
  l0Total: number;
  l0Workbench: L0Workbench | null;
  selectedSessionId: string | null;
  selectSession: (sessionId: string | null) => void;
  loadL0Sessions: (params?: PaginationParams & { status?: string; query?: string }) => Promise<boolean>;

  // L1 data
  l1Events: L1Event[];
  l1Total: number;
  queryL1Events: (params?: Omit<L1EventQueryParams, 'limit'> & { limit?: number }) => Promise<boolean>;

  // L2 data
  l2Relations: L2Relation[];
  l2RelationsTotal: number;
  l2Assertions: L2Assertion[];
  l2AssertionsTotal: number;
  l2Stats: L2Statistics;
  identityLinks: MemoryIdentityLink[];
  l2Entities: L2Entity[];
  l2EntitiesTotal: number;
  l2Mentions: L2Mention[];
  l2MentionsTotal: number;
  l2Snapshots: L2Snapshot[];
  l2SnapshotsTotal: number;
  l2ConflictRules: L2GraphConflictRule[];
  l2ActionLoading: boolean;
  submitManualL2Event: (payload: ManualL2EventPayload) => Promise<void>;
  replayL2Extraction: (eventId: string) => Promise<void>;
  flushL2Microbatches: () => Promise<void>;
  runL2Reconcile: (entityIds: string[]) => Promise<void>;
  runL2SnapshotRefresh: (entityIds: string[]) => Promise<void>;
  upsertL2GraphConflictRule: (payload: L2GraphConflictRulePayload) => Promise<void>;
  submitAssertionFeedback: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  loadL2Relations: (params?: MemoryListQueryParams) => Promise<boolean>;
  loadL2Assertions: (params?: MemoryListQueryParams) => Promise<boolean>;
  loadL2Entities: (params?: MemoryListQueryParams) => Promise<boolean>;
  loadL2Mentions: (params?: PaginationParams) => Promise<void>;
  loadL2Snapshots: (params?: MemoryListQueryParams) => Promise<boolean>;

  // L3 data
  l3Summaries: L3Summary[];
  l3Total: number;
  loadL3Summaries: (params?: MemoryListQueryParams) => Promise<boolean>;

  // L4 data
  l4Skills: L4Skill[];
  l4Total: number;
  loadL4Skills: (params?: MemoryListQueryParams) => Promise<boolean>;

  // Search
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  searchResults: MemorySearchResultPayload;
  searching: boolean;
  handleSearch: (queryMode?: MemorySearchQueryMode) => Promise<void>;

  // Clear dialog
  clearDialogOpen: boolean;
  setClearDialogOpen: (open: boolean) => void;
  clearing: boolean;
  handleClearRequest: () => void;
  handleClearConfirm: () => Promise<void>;

  // Actions
  refresh: (activeTab: string) => Promise<void>;
  refreshAll: () => Promise<void>;
}

export type MemoryInitialLoadScope = 'all' | 'overview' | 'l0' | 'l1' | 'l2' | 'l3' | 'l4';

export interface UseMemoryOptions {
  initialLoadScope?: MemoryInitialLoadScope;
}

const DEFAULT_STATS: MemoryStatistics = {
  l0: { active_sessions: 0, total_attention_items: 0 },
  l1: { event_count: 0 },
  l2: { relation_count: 0, assertion_count: 0 },
  l3: { summary_count: 0 },
  l4: { skill_count: 0, open_circuit_breakers: 0 },
};

const DEFAULT_L2_STATS: L2Statistics = {
  canonical_self_id: 'user:self',
  identity_link_count: 0,
  relation_count: 0,
  assertion_count: 0,
  extract_skipped: 0,
  extract_by_evidence_class: {},
  skip_by_reason: {},
};

const DEFAULT_SEARCH_RESULTS: MemorySearchResultPayload = {
  l0_workbench: [],
  l1_events: [],
  l1_evidence_bundles: [],
  l1_timeline_summary: [],
  l2_entity_cards: [],
  l2_relationships: [],
  l2_assertions: [],
  l2_episodes: [],
  l2_experiences: [],
  l2_state_facts: [],
  l2_state_history: [],
  l3_reflections: [],
  l4_procedures: [],
  structured_results: [],
  trace: {},
};

// ============================================================================
// Hook Implementation
// ============================================================================

export function useMemory(options: UseMemoryOptions = {}): UseMemoryReturn {
  const { initialLoadScope = 'all' } = options;
  const { t } = useTranslation('app');

  // Loading state
  const [loading, setLoading] = useState(false);

  // Statistics
  const [stats, setStats] = useState<MemoryStatistics>(DEFAULT_STATS);

  // L0 data
  const [l0Sessions, setL0Sessions] = useState<L0Session[]>([]);
  const [l0Total, setL0Total] = useState(0);
  const [l0Workbench, setL0Workbench] = useState<L0Workbench | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // L1 data
  const [l1Events, setL1Events] = useState<L1Event[]>([]);
  const [l1Total, setL1Total] = useState(0);

  // L2 data
  const [l2Relations, setL2Relations] = useState<L2Relation[]>([]);
  const [l2RelationsTotal, setL2RelationsTotal] = useState(0);
  const [l2Assertions, setL2Assertions] = useState<L2Assertion[]>([]);
  const [l2AssertionsTotal, setL2AssertionsTotal] = useState(0);
  const [l2Stats, setL2Stats] = useState<L2Statistics>(DEFAULT_L2_STATS);
  const [identityLinks, setIdentityLinks] = useState<MemoryIdentityLink[]>([]);
  const [l2Entities, setL2Entities] = useState<L2Entity[]>([]);
  const [l2EntitiesTotal, setL2EntitiesTotal] = useState(0);
  const [l2Mentions, setL2Mentions] = useState<L2Mention[]>([]);
  const [l2MentionsTotal, setL2MentionsTotal] = useState(0);
  const [l2Snapshots, setL2Snapshots] = useState<L2Snapshot[]>([]);
  const [l2SnapshotsTotal, setL2SnapshotsTotal] = useState(0);
  const [l2ConflictRules, setL2ConflictRules] = useState<L2GraphConflictRule[]>([]);
  const [l2ActionLoading, setL2ActionLoading] = useState(false);

  // L3 data
  const [l3Summaries, setL3Summaries] = useState<L3Summary[]>([]);
  const [l3Total, setL3Total] = useState(0);

  // L4 data
  const [l4Skills, setL4Skills] = useState<L4Skill[]>([]);
  const [l4Total, setL4Total] = useState(0);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemorySearchResultPayload>(DEFAULT_SEARCH_RESULTS);
  const [searching, setSearching] = useState(false);

  // Clear dialog state
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

  // ============================================================================
  // Data Loading Functions
  // ============================================================================

  const loadStatistics = useCallback(async () => {
    try {
      const data = await memoryApi.getStatistics();
      setStats(data);
      return true;
    } catch (error) {
      console.error('Failed to load statistics:', error);
      return false;
    }
  }, []);

  const loadL0Sessions = useCallback(async (params?: PaginationParams & { status?: string; query?: string }) => {
    try {
      const data = await memoryApi.getL0Sessions({ limit: 50, ...params });
      setL0Sessions(data.items || []);
      setL0Total(data.total ?? 0);
      return true;
    } catch (error) {
      console.error('Failed to load L0 sessions:', error);
      return false;
    }
  }, []);

  const loadL0Workbench = useCallback(async (sessionId: string) => {
    try {
      const data = await memoryApi.getL0Workbench(sessionId);
      setL0Workbench(data);
    } catch (error) {
      console.error('Failed to load L0 workbench:', error);
      setL0Workbench(null);
    }
  }, []);

  const loadL1Events = useCallback(async (params?: L1EventQueryParams) => {
    try {
      const data = await memoryApi.getL1Events({ limit: 50, ...params });
      setL1Events(data.items || []);
      setL1Total(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L1 events:', error);
      return false;
    }
  }, []);

  const queryL1Events = useCallback(
    async (params?: Omit<L1EventQueryParams, 'limit'> & { limit?: number }) => {
      setLoading(true);
      try {
        return await loadL1Events(params);
      } finally {
        setLoading(false);
      }
    },
    [loadL1Events]
  );

  const loadL2Relations = useCallback(async (params?: MemoryListQueryParams) => {
    try {
      const data = await memoryApi.getL2Relations({ limit: 50, ...params });
      setL2Relations(data.items || []);
      setL2RelationsTotal(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L2 relations:', error);
      return false;
    }
  }, []);

  const loadL2Assertions = useCallback(async (params?: MemoryListQueryParams) => {
    try {
      const data = await memoryApi.getL2Assertions({ limit: 50, ...params });
      setL2Assertions(data.items || []);
      setL2AssertionsTotal(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L2 assertions:', error);
      return false;
    }
  }, []);

  const loadL2Entities = useCallback(async (params?: MemoryListQueryParams) => {
    try {
      const data = await memoryApi.getL2Entities({ limit: 50, ...params });
      setL2Entities(data.items || []);
      setL2EntitiesTotal(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L2 entities:', error);
      return false;
    }
  }, []);

  const loadL2Mentions = useCallback(async (params?: PaginationParams) => {
    try {
      const data = await memoryApi.getL2Mentions({ limit: 50, ...params });
      setL2Mentions(data.items || []);
      setL2MentionsTotal(data.total || 0);
    } catch (error) {
      console.error('Failed to load L2 mentions:', error);
    }
  }, []);

  const loadL2Snapshots = useCallback(async (params?: MemoryListQueryParams) => {
    try {
      const data = await memoryApi.getL2Snapshots({ limit: 50, ...params });
      setL2Snapshots(data.items || []);
      setL2SnapshotsTotal(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L2 snapshots:', error);
      return false;
    }
  }, []);

  const loadL2Data = useCallback(async () => {
    try {
      const [l2StatsData, identityLinksData, relationsRes, assertionsRes, entitiesRes, mentionsRes, snapshotsRes, conflictRules] = await Promise.all([
        memoryApi.getL2Statistics(),
        memoryApi.getIdentityLinks(),
        memoryApi.getL2Relations({ limit: 50 }),
        memoryApi.getL2Assertions({ limit: 50 }),
        memoryApi.getL2Entities({ limit: 50 }),
        memoryApi.getL2Mentions({ limit: 50 }),
        memoryApi.getL2Snapshots({ limit: 50 }),
        memoryApi.getL2ConflictRules(),
      ]);
      setL2Stats(l2StatsData);
      setIdentityLinks(identityLinksData.links || []);
      setL2Relations(relationsRes.items || []);
      setL2RelationsTotal(relationsRes.total || 0);
      setL2Assertions(assertionsRes.items || []);
      setL2AssertionsTotal(assertionsRes.total || 0);
      setL2Entities(entitiesRes.items || []);
      setL2EntitiesTotal(entitiesRes.total || 0);
      setL2Mentions(mentionsRes.items || []);
      setL2MentionsTotal(mentionsRes.total || 0);
      setL2Snapshots(snapshotsRes.items || []);
      setL2SnapshotsTotal(snapshotsRes.total || 0);
      setL2ConflictRules(conflictRules);
      return true;
    } catch (error) {
      console.error('Failed to load L2 data:', error);
      return false;
    }
  }, []);

  const refreshL2Lab = useCallback(async () => {
    await Promise.all([loadStatistics(), loadL1Events(), loadL2Data()]);
  }, [loadStatistics, loadL1Events, loadL2Data]);

  const submitManualL2Event = useCallback(
    async (payload: ManualL2EventPayload) => {
      setL2ActionLoading(true);
      try {
        await memoryApi.createManualL2Event(payload);
        await refreshL2Lab();
        toast.success(t('memory.l2.lab.manualEventQueued'));
      } catch (error) {
        console.error('Failed to queue manual L2 event:', error);
        toast.error(t('memory.l2.lab.actionFailed'));
      } finally {
        setL2ActionLoading(false);
      }
    },
    [refreshL2Lab, t]
  );

  const replayL2Extraction = useCallback(
    async (eventId: string) => {
      if (!eventId) return;
      setL2ActionLoading(true);
      try {
        await memoryApi.replayL2Extraction(eventId);
        await refreshL2Lab();
        toast.success(t('memory.l2.lab.replayQueued'));
      } catch (error) {
        console.error('Failed to replay L2 extraction:', error);
        toast.error(t('memory.l2.lab.actionFailed'));
      } finally {
        setL2ActionLoading(false);
      }
    },
    [refreshL2Lab, t]
  );

  const flushL2Microbatches = useCallback(async () => {
    setL2ActionLoading(true);
    try {
      const response = await memoryApi.flushL2Microbatches();
      await refreshL2Lab();
      if ((response.batch_count ?? 0) > 0 || response.queued) {
        toast.success(t('memory.l2.lab.microbatchFlushQueued'));
      } else {
        toast.warning(t('memory.l2.lab.microbatchFlushIdle'));
      }
    } catch (error) {
      console.error('Failed to flush L2 microbatches:', error);
      toast.error(t('memory.l2.lab.actionFailed'));
    } finally {
      setL2ActionLoading(false);
    }
  }, [refreshL2Lab, t]);

  const runL2Reconcile = useCallback(
    async (entityIds: string[]) => {
      if (entityIds.length === 0) return;
      setL2ActionLoading(true);
      try {
        await memoryApi.reconcileL2Entities(entityIds);
        await refreshL2Lab();
        toast.success(t('memory.l2.lab.reconcileQueued'));
      } catch (error) {
        console.error('Failed to queue L2 reconcile:', error);
        toast.error(t('memory.l2.lab.actionFailed'));
      } finally {
        setL2ActionLoading(false);
      }
    },
    [refreshL2Lab, t]
  );

  const runL2SnapshotRefresh = useCallback(
    async (entityIds: string[]) => {
      if (entityIds.length === 0) return;
      setL2ActionLoading(true);
      try {
        await memoryApi.refreshL2Snapshots(entityIds);
        await refreshL2Lab();
        toast.success(t('memory.l2.lab.snapshotQueued'));
      } catch (error) {
        console.error('Failed to queue L2 snapshot refresh:', error);
        toast.error(t('memory.l2.lab.actionFailed'));
      } finally {
        setL2ActionLoading(false);
      }
    },
    [refreshL2Lab, t]
  );

  const upsertL2GraphConflictRule = useCallback(
    async (payload: L2GraphConflictRulePayload) => {
      if (!payload.predicate.trim()) return;
      setL2ActionLoading(true);
      try {
        await memoryApi.upsertL2ConflictRule({
          ...payload,
          predicate: payload.predicate.trim(),
          exclusive_group: payload.exclusive_group?.trim() || null,
        });
        await refreshL2Lab();
        toast.success(t('memory.l2.lab.ruleSaved'));
      } catch (error) {
        console.error('Failed to update graph conflict rule:', error);
        toast.error(t('memory.l2.lab.actionFailed'));
      } finally {
        setL2ActionLoading(false);
      }
    },
    [refreshL2Lab, t]
  );

  const submitAssertionFeedback = useCallback(
    async (assertionId: string, feedback: 'confirmed') => {
      setL2ActionLoading(true);
      try {
        await memoryApi.submitAssertionFeedback(assertionId, feedback);
        await refreshL2Lab();
        toast.success(t('memory.l2.feedbackConfirmed'));
      } catch (error) {
        console.error('Failed to submit assertion feedback:', error);
        toast.error(t('memory.l2.lab.actionFailed'));
      } finally {
        setL2ActionLoading(false);
      }
    },
    [refreshL2Lab, t]
  );

  const loadL3Summaries = useCallback(async (params?: MemoryListQueryParams) => {
    try {
      const data = await memoryApi.getL3Summaries({ limit: 50, ...params });
      setL3Summaries(data.items || []);
      setL3Total(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L3 summaries:', error);
      return false;
    }
  }, []);

  const loadL4Skills = useCallback(async (params?: MemoryListQueryParams) => {
    try {
      const data = await memoryApi.getL4Skills({ limit: 50, ...params });
      setL4Skills(data.items || []);
      setL4Total(data.total || 0);
      return true;
    } catch (error) {
      console.error('Failed to load L4 skills:', error);
      return false;
    }
  }, []);

  const loadInitialScope = useCallback(async () => {
    const jobs: Promise<unknown>[] = [];

    switch (initialLoadScope) {
      case 'all':
        jobs.push(loadStatistics());
        jobs.push(loadL0Sessions(), loadL1Events(), loadL2Data(), loadL3Summaries(), loadL4Skills());
        break;
      case 'overview':
        jobs.push(loadStatistics());
        break;
      case 'l0':
        jobs.push(loadStatistics());
        jobs.push(loadL0Sessions());
        break;
      case 'l1':
        jobs.push(loadStatistics());
        jobs.push(loadL1Events());
        break;
      case 'l2':
        jobs.push(loadStatistics());
        jobs.push(loadL1Events(), loadL2Data());
        break;
      case 'l3':
        jobs.push(loadStatistics());
        jobs.push(loadL3Summaries());
        break;
      case 'l4':
        jobs.push(loadStatistics());
        jobs.push(loadL4Skills());
        break;
    }

    await Promise.all(jobs);
  }, [initialLoadScope, loadStatistics, loadL0Sessions, loadL1Events, loadL2Data, loadL3Summaries, loadL4Skills]);

  // ============================================================================
  // Initial Load
  // ============================================================================

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await loadInitialScope();
      setLoading(false);
    };
    void loadAll();
  }, [loadInitialScope]);

  // ============================================================================
  // Session Selection
  // ============================================================================

  useEffect(() => {
    if (selectedSessionId) {
      loadL0Workbench(selectedSessionId);
    }
  }, [selectedSessionId, loadL0Workbench]);

  const selectSession = useCallback((sessionId: string | null) => {
    setSelectedSessionId(sessionId);
  }, []);

  // ============================================================================
  // Refresh Actions
  // ============================================================================

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.all([
        loadStatistics(),
        loadL0Sessions(),
        loadL1Events(),
        loadL2Data(),
        loadL3Summaries(),
        loadL4Skills(),
      ]);
      if (results.some((succeeded) => !succeeded)) {
        throw new Error('One or more memory views failed to refresh');
      }
    } finally {
      setLoading(false);
    }
  }, [loadStatistics, loadL0Sessions, loadL1Events, loadL2Data, loadL3Summaries, loadL4Skills]);

  const refresh = useCallback(
    async (activeTab: string) => {
      setLoading(true);
      await loadStatistics();
      switch (activeTab) {
        case 'l0':
          await loadL0Sessions();
          if (selectedSessionId) {
            await loadL0Workbench(selectedSessionId);
          }
          break;
        case 'l1':
          await loadL1Events();
          break;
        case 'l2':
          await loadL2Data();
          break;
        case 'l3':
          await loadL3Summaries();
          break;
        case 'l4':
          await loadL4Skills();
          break;
      }
      setLoading(false);
      toast.success(t('memory.refreshSuccess'));
    },
    [loadStatistics, loadL0Sessions, loadL0Workbench, loadL1Events, loadL2Data, loadL3Summaries, loadL4Skills, selectedSessionId, t]
  );

  // ============================================================================
  // Search
  // ============================================================================

  const handleSearch = useCallback(async (queryMode?: MemorySearchQueryMode) => {
    if (!searchQuery.trim()) {
      setSearchResults(DEFAULT_SEARCH_RESULTS);
      return;
    }
    setSearching(true);
    try {
      const results = await memoryApi.search(searchQuery, { query_mode: queryMode });
      setSearchResults(results);
      toast.success(t('memory.searchComplete'));
    } catch (error) {
      setSearchResults(DEFAULT_SEARCH_RESULTS);
      toast.error(t('memory.searchError', { message: String(error) }));
    } finally {
      setSearching(false);
    }
  }, [searchQuery, t]);

  // ============================================================================
  // Clear Memory
  // ============================================================================

  const handleClearRequest = useCallback(() => {
    setClearDialogOpen(true);
  }, []);

  const resetMemoryView = useCallback(() => {
    setStats(DEFAULT_STATS);
    setL0Sessions([]);
    setL0Total(0);
    setL0Workbench(null);
    setSelectedSessionId(null);
    setL1Events([]);
    setL1Total(0);
    setL2Relations([]);
    setL2RelationsTotal(0);
    setL2Assertions([]);
    setL2AssertionsTotal(0);
    setL2Stats(DEFAULT_L2_STATS);
    setIdentityLinks([]);
    setL2Entities([]);
    setL2EntitiesTotal(0);
    setL2Mentions([]);
    setL2MentionsTotal(0);
    setL2Snapshots([]);
    setL2SnapshotsTotal(0);
    setL2ConflictRules([]);
    setL3Summaries([]);
    setL3Total(0);
    setL4Skills([]);
    setL4Total(0);
    setSearchQuery('');
    setSearchResults(DEFAULT_SEARCH_RESULTS);
  }, []);

  const handleClearConfirm = useCallback(async () => {
    setClearing(true);
    let result: Awaited<ReturnType<typeof clearAllMemory>>;
    try {
      result = await clearAllMemory();
    } catch {
      setClearing(false);
      toast.error(t('memory.clearFailed'));
      return;
    }

    resetMemoryView();
    const feedback = summarizeMemoryClear(result);
    toast.success(t('memory.clearSuccess', {
      count: feedback.clearedItemCount,
    }));
    if (feedback.recoveryPending) {
      toast.warning(t('memory.clearRecoveryPending'));
    }
    if (feedback.otherWarningsPresent) {
      toast.warning(t('memory.clearCompletedWithWarnings'));
    }
    setClearDialogOpen(false);
    try {
      await refreshAll();
    } catch {
      toast.warning(t('memory.clearRefreshFailed'));
    } finally {
      setClearing(false);
    }
  }, [refreshAll, resetMemoryView, t]);

  // ============================================================================
  // Return
  // ============================================================================

  return {
    // Loading state
    loading,

    // Statistics
    stats,

    // L0 data
    l0Sessions,
    l0Total,
    l0Workbench,
    selectedSessionId,
    selectSession,
    loadL0Sessions,

    // L1 data
    l1Events,
    l1Total,
    queryL1Events,

    // L2 data
    l2Relations,
    l2RelationsTotal,
    l2Assertions,
    l2AssertionsTotal,
    l2Stats,
    identityLinks,
    l2Entities,
    l2EntitiesTotal,
    l2Mentions,
    l2MentionsTotal,
    l2Snapshots,
    l2SnapshotsTotal,
    l2ConflictRules,
    l2ActionLoading,
    submitManualL2Event,
    replayL2Extraction,
    flushL2Microbatches,
    runL2Reconcile,
    runL2SnapshotRefresh,
    upsertL2GraphConflictRule,
    submitAssertionFeedback,
    loadL2Relations,
    loadL2Assertions,
    loadL2Entities,
    loadL2Mentions,
    loadL2Snapshots,

    // L3 data
    l3Summaries,
    l3Total,
    loadL3Summaries,

    // L4 data
    l4Skills,
    l4Total,
    loadL4Skills,

    // Search
    searchQuery,
    setSearchQuery,
    searchResults,
    searching,
    handleSearch,

    // Clear dialog
    clearDialogOpen,
    setClearDialogOpen,
    clearing,
    handleClearRequest,
    handleClearConfirm,

    // Actions
    refresh,
    refreshAll,
  };
}

// ============================================================================
// Utilities
// ============================================================================

export const formatTimestamp = (ts: number): string => {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString();
};
