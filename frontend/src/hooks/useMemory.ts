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
import type {
  L0Session,
  L0Workbench,
  L1Event,
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
  l0Workbench: L0Workbench | null;
  selectedSessionId: string | null;
  selectSession: (sessionId: string | null) => void;

  // L1 data
  l1Events: L1Event[];

  // L2 data
  l2Relations: L2Relation[];
  l2Assertions: L2Assertion[];
  l2Stats: L2Statistics;
  identityLinks: MemoryIdentityLink[];
  l2Entities: L2Entity[];
  l2Mentions: L2Mention[];
  l2Snapshots: L2Snapshot[];
  l2ConflictRules: L2GraphConflictRule[];
  l2ActionLoading: boolean;
  submitManualL2Event: (payload: ManualL2EventPayload) => Promise<void>;
  replayL2Extraction: (eventId: string) => Promise<void>;
  runL2Reconcile: (entityIds: string[]) => Promise<void>;
  runL2SnapshotRefresh: (entityIds: string[]) => Promise<void>;
  upsertL2GraphConflictRule: (payload: L2GraphConflictRulePayload) => Promise<void>;

  // L3 data
  l3Summaries: L3Summary[];

  // L4 data
  l4Skills: L4Skill[];

  // Search
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  searching: boolean;
  handleSearch: () => Promise<void>;

  // Clear dialog
  clearDialogOpen: boolean;
  setClearDialogOpen: (open: boolean) => void;
  clearConfirmText: string;
  setClearConfirmText: (text: string) => void;
  clearing: boolean;
  handleClearRequest: () => void;
  handleClearConfirm: () => Promise<void>;

  // Actions
  refresh: (activeTab: string) => Promise<void>;
  refreshAll: () => Promise<void>;
}

const DEFAULT_STATS: MemoryStatistics = {
  l0: { active_sessions: 0, total_goals: 0, total_entities: 0, total_tactics: 0 },
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

// ============================================================================
// Hook Implementation
// ============================================================================

export function useMemory(): UseMemoryReturn {
  const { t } = useTranslation('app');

  // Loading state
  const [loading, setLoading] = useState(false);

  // Statistics
  const [stats, setStats] = useState<MemoryStatistics>(DEFAULT_STATS);

  // L0 data
  const [l0Sessions, setL0Sessions] = useState<L0Session[]>([]);
  const [l0Workbench, setL0Workbench] = useState<L0Workbench | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // L1 data
  const [l1Events, setL1Events] = useState<L1Event[]>([]);

  // L2 data
  const [l2Relations, setL2Relations] = useState<L2Relation[]>([]);
  const [l2Assertions, setL2Assertions] = useState<L2Assertion[]>([]);
  const [l2Stats, setL2Stats] = useState<L2Statistics>(DEFAULT_L2_STATS);
  const [identityLinks, setIdentityLinks] = useState<MemoryIdentityLink[]>([]);
  const [l2Entities, setL2Entities] = useState<L2Entity[]>([]);
  const [l2Mentions, setL2Mentions] = useState<L2Mention[]>([]);
  const [l2Snapshots, setL2Snapshots] = useState<L2Snapshot[]>([]);
  const [l2ConflictRules, setL2ConflictRules] = useState<L2GraphConflictRule[]>([]);
  const [l2ActionLoading, setL2ActionLoading] = useState(false);

  // L3 data
  const [l3Summaries, setL3Summaries] = useState<L3Summary[]>([]);

  // L4 data
  const [l4Skills, setL4Skills] = useState<L4Skill[]>([]);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searching, setSearching] = useState(false);

  // Clear dialog state
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [clearConfirmText, setClearConfirmText] = useState('');
  const [clearing, setClearing] = useState(false);

  // ============================================================================
  // Data Loading Functions
  // ============================================================================

  const loadStatistics = useCallback(async () => {
    try {
      const data = await memoryApi.getStatistics();
      setStats(data);
    } catch (error) {
      console.error('Failed to load statistics:', error);
    }
  }, []);

  const loadL0Sessions = useCallback(async () => {
    try {
      const data = await memoryApi.getL0Sessions();
      setL0Sessions(data.sessions || []);
    } catch (error) {
      console.error('Failed to load L0 sessions:', error);
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

  const loadL1Events = useCallback(async () => {
    try {
      const data = await memoryApi.getL1Events({ limit: 100 });
      setL1Events(data.events || []);
    } catch (error) {
      console.error('Failed to load L1 events:', error);
    }
  }, []);

  const loadL2Data = useCallback(async () => {
    try {
      const [l2StatsData, identityLinksData, relations, assertions, entities, mentions, snapshots, conflictRules] = await Promise.all([
        memoryApi.getL2Statistics(),
        memoryApi.getIdentityLinks(),
        memoryApi.getL2Relations(100),
        memoryApi.getL2Assertions(100),
        memoryApi.getL2Entities(100),
        memoryApi.getL2Mentions(100),
        memoryApi.getL2Snapshots(100),
        memoryApi.getL2ConflictRules(),
      ]);
      setL2Stats(l2StatsData);
      setIdentityLinks(identityLinksData.links || []);
      setL2Relations(relations);
      setL2Assertions(assertions);
      setL2Entities(entities);
      setL2Mentions(mentions);
      setL2Snapshots(snapshots);
      setL2ConflictRules(conflictRules);
    } catch (error) {
      console.error('Failed to load L2 data:', error);
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

  const loadL3Summaries = useCallback(async () => {
    try {
      const data = await memoryApi.getL3Summaries({ limit: 100 });
      setL3Summaries(data);
    } catch (error) {
      console.error('Failed to load L3 summaries:', error);
    }
  }, []);

  const loadL4Skills = useCallback(async () => {
    try {
      const data = await memoryApi.getL4Skills(100);
      setL4Skills(data);
    } catch (error) {
      console.error('Failed to load L4 skills:', error);
    }
  }, []);

  // ============================================================================
  // Initial Load
  // ============================================================================

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await Promise.all([
        loadStatistics(),
        loadL0Sessions(),
        loadL1Events(),
        loadL2Data(),
        loadL3Summaries(),
        loadL4Skills(),
      ]);
      setLoading(false);
    };
    loadAll();
  }, [loadStatistics, loadL0Sessions, loadL1Events, loadL2Data, loadL3Summaries, loadL4Skills]);

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
    await Promise.all([
      loadStatistics(),
      loadL0Sessions(),
      loadL1Events(),
      loadL2Data(),
      loadL3Summaries(),
      loadL4Skills(),
    ]);
    setLoading(false);
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

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const results = await memoryApi.search(searchQuery);
      toast.success(t('memory.searchComplete'));
      console.log('Search results:', results);
    } catch (error) {
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
    setClearConfirmText('');
  }, []);

  const handleClearConfirm = useCallback(async () => {
    if (clearConfirmText !== 'CLEAR') return;
    setClearing(true);
    try {
      const result = await memoryApi.clearAll();
      toast.success(`Cleared ${result.results?.l0?.count || 0} items`);
      setClearDialogOpen(false);
      await refreshAll();
    } catch (error) {
      toast.error(`Clear failed: ${error}`);
    } finally {
      setClearing(false);
    }
  }, [clearConfirmText, refreshAll]);

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
    l0Workbench,
    selectedSessionId,
    selectSession,

    // L1 data
    l1Events,

    // L2 data
    l2Relations,
    l2Assertions,
    l2Stats,
    identityLinks,
    l2Entities,
    l2Mentions,
    l2Snapshots,
    l2ConflictRules,
    l2ActionLoading,
    submitManualL2Event,
    replayL2Extraction,
    runL2Reconcile,
    runL2SnapshotRefresh,
    upsertL2GraphConflictRule,

    // L3 data
    l3Summaries,

    // L4 data
    l4Skills,

    // Search
    searchQuery,
    setSearchQuery,
    searching,
    handleSearch,

    // Clear dialog
    clearDialogOpen,
    setClearDialogOpen,
    clearConfirmText,
    setClearConfirmText,
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
