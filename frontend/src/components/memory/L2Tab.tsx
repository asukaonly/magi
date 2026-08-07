/**
 * L2Tab - L2 cognition workspace rendered as focused in-page sections.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { DatabaseZap, RefreshCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  memoryApi,
  type L1Event,
  type L2Assertion,
  type L2Entity,
  type L2GraphConflictRule,
  type MemoryIdentityLink,
  type L2GraphConflictRulePayload,
  type L2Mention,
  type L2Relation,
  type L2Snapshot,
  type L2Statistics,
  type ManualL2EventPayload,
} from '@/api/modules/memory';
import {
  buildEntityOverviewItems,
  buildKnowledgeBaseGroups,
  buildKnowledgeItems,
  buildSelfEntityAliasSet,
  filterKnowledgeItems,
  type EntityOverviewItem,
  type KnowledgeBaseGroup,
  type KnowledgeBaseGroupId,
  type KnowledgeCorrectionAction,
  type KnowledgeItem,
} from './l2KnowledgeModel';
import { L2ConflictRulesSection } from './l2/L2ConflictRulesSection';
import {
  L2CanonicalEntitiesSection,
  L2KnowledgeGraphSection,
  L2MindSnapshotsSection,
  L2RecentMentionsSection,
  L2TheoryOfMindSection,
} from './l2/L2InspectorSections';
import { EntityOverviewPanel, KnowledgeBaseBrowser, KnowledgeListPanel } from './l2/L2KnowledgePanels';
import { L2LabSection } from './l2/L2LabSection';
import { BreakdownCard } from './l2/L2Primitives';

export type L2KnowledgeSection =
  | 'overview'
  | 'knowledgeBase'
  | 'advanced'
  | 'knowledgeGraph'
  | 'theoryOfMind'
  | 'mindSnapshots'
  | 'lab'
  | 'canonicalEntities'
  | 'recentMentions'
  | 'conflictRules';

interface L2TabProps {
  section?: L2KnowledgeSection;
  stats: L2Statistics;
  relations: L2Relation[];
  assertions: L2Assertion[];
  identityLinks: MemoryIdentityLink[];
  entities: L2Entity[];
  mentions: L2Mention[];
  snapshots: L2Snapshot[];
  conflictRules: L2GraphConflictRule[];
  events: L1Event[];
  dominantPredicates?: Array<[string, number]>;
  knowledgeQuery?: string;
  knowledgeStatusFilter?: string;
  knowledgeEntityTypeFilter?: string;
  actionLoading: boolean;
  onFlushProjectionJobs?: () => Promise<void>;
  onSubmitManualEvent: (payload: ManualL2EventPayload) => Promise<void>;
  onReplayExtraction: (eventId: string) => Promise<void>;
  onRunReconcile: (entityIds: string[]) => Promise<void>;
  onRunSnapshotRefresh: (entityIds: string[]) => Promise<void>;
  onUpsertGraphConflictRule: (payload: L2GraphConflictRulePayload) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
}


export const L2Tab: React.FC<L2TabProps> = ({
  section = 'lab',
  stats,
  relations,
  assertions,
  identityLinks,
  entities,
  mentions,
  snapshots,
  conflictRules,
  events,
  dominantPredicates = [],
  knowledgeQuery = '',
  knowledgeStatusFilter = 'all',
  knowledgeEntityTypeFilter = 'all',
  actionLoading,
  onFlushProjectionJobs,
  onSubmitManualEvent,
  onReplayExtraction,
  onRunReconcile,
  onRunSnapshotRefresh,
  onUpsertGraphConflictRule,
  onSubmitAssertionFeedback,
  onRequestAssertionCorrection,
}) => {
  const { t } = useTranslation('app');
  const [selectedKnowledgeGroupId, setSelectedKnowledgeGroupId] = useState<KnowledgeBaseGroupId>('aboutSelf');
  const [fetchedEvidenceEvents, setFetchedEvidenceEvents] = useState<Record<string, L1Event | null>>({});
  const [loadingEvidenceIds, setLoadingEvidenceIds] = useState<Record<string, boolean>>({});

  const entityById = useMemo(
    () => new Map(entities.map((entity) => [entity.entity_id, entity] as const)),
    [entities]
  );

  const selfEntityAliases = useMemo(
    () => buildSelfEntityAliasSet(stats.canonical_self_id, identityLinks),
    [identityLinks, stats.canonical_self_id]
  );

  const visibleEventById = useMemo(
    () => new Map(events.map((event) => [event.event_id, event] as const)),
    [events]
  );

  const evidenceEventsById = useMemo(() => {
    const merged = new Map<string, L1Event | null>(fetchedEvidenceEvents ? Object.entries(fetchedEvidenceEvents) : []);
    visibleEventById.forEach((event, eventId) => merged.set(eventId, event));
    return merged;
  }, [fetchedEvidenceEvents, visibleEventById]);

  const loadEvidenceEvents = useCallback(
    async (eventIds: string[]) => {
      const missingIds = eventIds
        .filter((eventId) => eventId && !evidenceEventsById.has(eventId) && !loadingEvidenceIds[eventId])
        .slice(0, 8);
      if (missingIds.length === 0) {
        return;
      }

      setLoadingEvidenceIds((current) => ({
        ...current,
        ...Object.fromEntries(missingIds.map((eventId) => [eventId, true])),
      }));

      try {
        const results = await Promise.all(
          missingIds.map(async (eventId) => {
            const response = await memoryApi.getL1Events({ event_id: eventId, limit: 1 });
            return [eventId, response.items?.[0] ?? null] as const;
          })
        );
        setFetchedEvidenceEvents((current) => ({
          ...current,
          ...Object.fromEntries(results),
        }));
      } catch (error) {
        console.error('Failed to load L1 evidence events:', error);
      } finally {
        setLoadingEvidenceIds((current) => {
          const next = { ...current };
          missingIds.forEach((eventId) => {
            delete next[eventId];
          });
          return next;
        });
      }
    },
    [evidenceEventsById, loadingEvidenceIds]
  );

  const evidenceBreakdownEntries = useMemo(
    () => Object.entries(stats.extract_by_evidence_class || {}).sort((left, right) => right[1] - left[1]),
    [stats.extract_by_evidence_class]
  );

  const skipReasonEntries = useMemo(
    () => Object.entries(stats.skip_by_reason || {}).sort((left, right) => right[1] - left[1]),
    [stats.skip_by_reason]
  );

  const entityTypeBreakdown = useMemo(
    () =>
      Array.from(
        entities.reduce((map, entity) => {
          map.set(entity.entity_type, (map.get(entity.entity_type) ?? 0) + 1);
          return map;
        }, new Map<string, number>())
      ).sort((left, right) => right[1] - left[1]),
    [entities]
  );

  const dominantTraits = useMemo(
    () =>
      Array.from(
        assertions.reduce((map, assertion) => {
          map.set(assertion.trait_name, (map.get(assertion.trait_name) ?? 0) + 1);
          return map;
        }, new Map<string, number>())
      ).sort((left, right) => right[1] - left[1]),
    [assertions]
  );

  const knowledgeItems = useMemo<KnowledgeItem[]>(
    () => buildKnowledgeItems({ relations, assertions, entityById, selfEntityAliases, t }),
    [assertions, entityById, relations, selfEntityAliases, t]
  );

  const filteredKnowledgeItems = useMemo(
    () => filterKnowledgeItems(knowledgeItems, {
      query: knowledgeQuery,
      statusFilter: knowledgeStatusFilter,
      entityTypeFilter: knowledgeEntityTypeFilter,
    }),
    [knowledgeEntityTypeFilter, knowledgeItems, knowledgeQuery, knowledgeStatusFilter]
  );

  const knowledgeBaseGroups = useMemo<KnowledgeBaseGroup[]>(
    () => buildKnowledgeBaseGroups(filteredKnowledgeItems, t),
    [filteredKnowledgeItems, t]
  );

  const selectedKnowledgeGroup = knowledgeBaseGroups.find((group) => group.id === selectedKnowledgeGroupId) ?? knowledgeBaseGroups[0];
  const selectedKnowledgeGroupItems = selectedKnowledgeGroup?.items ?? [];
  const selectedKnowledgeReviewItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted');
  const selectedKnowledgeStableItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'active' && item.kind === 'assertion');
  const selectedKnowledgeRelationItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'active' && item.kind === 'relation');
  const selectedKnowledgeDeprecatedItems = selectedKnowledgeGroupItems.filter((item) => item.statusGroup === 'deprecated');

  const activeKnowledgeItems = knowledgeItems.filter((item) => item.statusGroup === 'active');
  const reviewKnowledgeItems = knowledgeItems.filter((item) => item.statusGroup === 'needsReview' || item.statusGroup === 'conflicted');
  const entityOverviewItems = useMemo<EntityOverviewItem[]>(
    () => buildEntityOverviewItems({ entities, entityById, snapshots, knowledgeItems, selfEntityAliases, t }),
    [entities, entityById, knowledgeItems, selfEntityAliases, snapshots, t]
  );
  const reviewItems = reviewKnowledgeItems.slice(0, 6);
  const overviewEntities = entityOverviewItems.slice(0, 8);

  const renderOverview = () => (
    <div className="space-y-4">
      <section className="border-b border-[hsl(var(--memory-divider)/0.58)] pb-4">
        <p className="text-base font-medium leading-7 text-[hsl(var(--memory-title))]">
          {t('memory.pages.knowledge.overview.summary', {
            total: activeKnowledgeItems.length,
            review: reviewKnowledgeItems.length,
            entities: entityOverviewItems.length,
          })}
        </p>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-[hsl(var(--memory-body))]">
          {t('memory.pages.knowledge.overview.guidance')}
        </p>
      </section>

      {reviewItems.length > 0 ? (
        <KnowledgeListPanel
          title={t('memory.pages.knowledge.sections.reviewQueue')}
          emptyText={t('memory.pages.knowledge.emptyReviewQueue')}
          items={reviewItems}
          count={reviewKnowledgeItems.length}
          actionLoading={actionLoading}
          evidenceEventsById={evidenceEventsById}
          loadingEvidenceIds={loadingEvidenceIds}
          onLoadEvidenceEvents={loadEvidenceEvents}
          onSubmitAssertionFeedback={onSubmitAssertionFeedback}
          onRequestAssertionCorrection={onRequestAssertionCorrection}
          t={t}
        />
      ) : null}
      <EntityOverviewPanel
        title={t('memory.pages.knowledge.sections.entityOverview')}
        emptyText={t('memory.pages.knowledge.emptyEntityOverview')}
        items={overviewEntities}
        count={entityOverviewItems.length}
        actionLoading={actionLoading}
        evidenceEventsById={evidenceEventsById}
        loadingEvidenceIds={loadingEvidenceIds}
        onLoadEvidenceEvents={loadEvidenceEvents}
        onSubmitAssertionFeedback={onSubmitAssertionFeedback}
        onRequestAssertionCorrection={onRequestAssertionCorrection}
        t={t}
      />
    </div>
  );

  const renderKnowledgeBase = () => (
    <div className="space-y-4">
      <KnowledgeBaseBrowser
        groups={knowledgeBaseGroups}
        selectedGroupId={selectedKnowledgeGroup?.id ?? 'all'}
        selectedGroup={selectedKnowledgeGroup}
        reviewItems={selectedKnowledgeReviewItems}
        stableItems={selectedKnowledgeStableItems}
        relationItems={selectedKnowledgeRelationItems}
        deprecatedItems={selectedKnowledgeDeprecatedItems}
        emptyText={t('memory.pages.knowledge.emptyKnowledge')}
        actionLoading={actionLoading}
        evidenceEventsById={evidenceEventsById}
        loadingEvidenceIds={loadingEvidenceIds}
        onLoadEvidenceEvents={loadEvidenceEvents}
        onSubmitAssertionFeedback={onSubmitAssertionFeedback}
        onRequestAssertionCorrection={onRequestAssertionCorrection}
        onSelectGroup={setSelectedKnowledgeGroupId}
        t={t}
      />
    </div>
  );

  const renderAdvanced = () => (
    <div className="space-y-4">
      <section className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.78)] px-4 py-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.pages.knowledge.sections.maintenance')}</h2>
            <p className="mt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">{t('memory.pages.knowledge.advancedHint')}</p>
          </div>
          {onFlushProjectionJobs ? (
            <Button
              variant="outline"
              className="h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 text-sm text-[hsl(var(--memory-title))]"
              onClick={() => void onFlushProjectionJobs()}
              disabled={actionLoading}
            >
              {actionLoading ? <RefreshCcw className="mr-2 h-4 w-4 animate-spin" /> : <DatabaseZap className="mr-2 h-4 w-4" />}
              {t('memory.pages.knowledge.actions.flushMicrobatches')}
            </Button>
          ) : null}
        </div>
      </section>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3" open>
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.title')}</summary>
        <div className="mt-4">{renderLab()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.entities')}</summary>
        <div className="mt-4">{renderCanonicalEntities()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.mentions')}</summary>
        <div className="mt-4">{renderRecentMentions()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.l2.lab.conflictRules')}</summary>
        <div className="mt-4">{renderConflictRules()}</div>
      </details>

      <details className="rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.62)] px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.pages.knowledge.sections.diagnostics')}</summary>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          <BreakdownCard
            title={t('memory.pages.knowledge.sections.entityTypes')}
            emptyText={t('memory.pages.knowledge.focusAll')}
            entries={entityTypeBreakdown}
          />
          <BreakdownCard
            title={t('memory.pages.knowledge.sections.structureOverview')}
            emptyText={t('memory.l2.noRelations')}
            entries={dominantPredicates.slice(0, 8)}
          />
          <BreakdownCard
            title={t('memory.l2.lab.evidenceBreakdown')}
            emptyText={t('memory.l2.lab.noEvidenceBreakdown')}
            entries={evidenceBreakdownEntries}
          />
          <BreakdownCard
            title={t('memory.l2.lab.skipReasonBreakdown')}
            emptyText={t('memory.l2.lab.noSkipReasons')}
            entries={skipReasonEntries}
          />
        </div>
      </details>
    </div>
  );

  const renderKnowledgeGraph = () => (
    <L2KnowledgeGraphSection relations={relations} t={t} />
  );

  const renderTheoryOfMind = () => (
    <L2TheoryOfMindSection
      actionLoading={actionLoading}
      assertions={assertions}
      dominantTraits={dominantTraits}
      onSubmitAssertionFeedback={onSubmitAssertionFeedback}
      onRequestAssertionCorrection={onRequestAssertionCorrection
        ? (assertion, action) => {
            const item = knowledgeItems.find((candidate) => candidate.assertionId === assertion.assertion_id);
            if (item) onRequestAssertionCorrection(item, action);
          }
        : undefined}
      t={t}
    />
  );

  const renderMindSnapshots = () => (
    <L2MindSnapshotsSection snapshots={snapshots} t={t} />
  );

  const renderLab = () => (
    <L2LabSection
      actionLoading={actionLoading}
      entities={entities}
      events={events}
      onSubmitManualEvent={onSubmitManualEvent}
      onReplayExtraction={onReplayExtraction}
      onRunReconcile={onRunReconcile}
      onRunSnapshotRefresh={onRunSnapshotRefresh}
      t={t}
    />
  );

  const renderCanonicalEntities = () => (
    <L2CanonicalEntitiesSection
      entities={entities}
      entityTypeBreakdown={entityTypeBreakdown}
      t={t}
    />
  );

  const renderRecentMentions = () => (
    <L2RecentMentionsSection events={events} mentions={mentions} t={t} />
  );

  const renderConflictRules = () => (
    <L2ConflictRulesSection
      actionLoading={actionLoading}
      conflictRules={conflictRules}
      onUpsertGraphConflictRule={onUpsertGraphConflictRule}
      t={t}
    />
  );

  switch (section) {
    case 'overview':
      return renderOverview();
    case 'knowledgeBase':
      return renderKnowledgeBase();
    case 'advanced':
      return renderAdvanced();
    case 'knowledgeGraph':
      return renderKnowledgeGraph();
    case 'theoryOfMind':
      return renderTheoryOfMind();
    case 'mindSnapshots':
      return renderMindSnapshots();
    case 'lab':
      return renderLab();
    case 'canonicalEntities':
      return renderCanonicalEntities();
    case 'recentMentions':
      return renderRecentMentions();
    case 'conflictRules':
      return renderConflictRules();
    default:
      return null;
  }
};

export default L2Tab;
