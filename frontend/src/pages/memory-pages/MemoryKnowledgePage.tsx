import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L2Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, { MEMORY_FILTER_INPUT_CLASS, MEMORY_FILTER_SELECT_CLASS, MemoryHeroStat } from './MemoryPageFrame';

export const MemoryKnowledgePage = () => {
  const { t } = useTranslation('app');
  const {
    loading,
    l1Events,
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
    refresh,
  } = useMemory();
  const [query, setQuery] = useState('');
  const [entityTypeFilter, setEntityTypeFilter] = useState('all');

  const entityTypes = useMemo(
    () => Array.from(new Set(l2Entities.map((entity) => entity.entity_type).filter(Boolean))).sort(),
    [l2Entities]
  );

  const normalizedQuery = query.trim().toLowerCase();

  const filteredEntities = useMemo(
    () =>
      l2Entities.filter((entity) => {
        const matchesQuery =
          normalizedQuery.length === 0 ||
          entity.canonical_name.toLowerCase().includes(normalizedQuery) ||
          entity.entity_id.toLowerCase().includes(normalizedQuery);
        const matchesType = entityTypeFilter === 'all' || entity.entity_type === entityTypeFilter;
        return matchesQuery && matchesType;
      }),
    [entityTypeFilter, l2Entities, normalizedQuery]
  );

  const visibleEntityIds = useMemo(
    () => new Set(filteredEntities.map((entity) => entity.entity_id)),
    [filteredEntities]
  );

  const filteredRelations = useMemo(
    () =>
      l2Relations.filter((relation) => {
        const matchesQuery =
          normalizedQuery.length === 0 ||
          relation.subject_id.toLowerCase().includes(normalizedQuery) ||
          relation.object_id.toLowerCase().includes(normalizedQuery) ||
          relation.predicate.toLowerCase().includes(normalizedQuery);
        const matchesType =
          entityTypeFilter === 'all' ||
          relation.subject_type === entityTypeFilter ||
          relation.object_type === entityTypeFilter;
        return matchesQuery && matchesType;
      }),
    [entityTypeFilter, l2Relations, normalizedQuery]
  );

  const filteredAssertions = useMemo(
    () =>
      l2Assertions.filter((assertion) => {
        const matchesQuery =
          normalizedQuery.length === 0 ||
          assertion.entity_id.toLowerCase().includes(normalizedQuery) ||
          assertion.trait_name.toLowerCase().includes(normalizedQuery) ||
          assertion.trait_value.toLowerCase().includes(normalizedQuery);
        const matchesType = entityTypeFilter === 'all' || assertion.entity_type === entityTypeFilter;
        return matchesQuery && matchesType;
      }),
    [entityTypeFilter, l2Assertions, normalizedQuery]
  );

  const filteredMentions = useMemo(
    () =>
      l2Mentions.filter((mention) => {
        const matchesQuery =
          normalizedQuery.length === 0 ||
          mention.mention_text.toLowerCase().includes(normalizedQuery) ||
          mention.resolved_entity_id?.toLowerCase().includes(normalizedQuery);
        const matchesType = entityTypeFilter === 'all' || mention.entity_type === entityTypeFilter;
        return matchesQuery && matchesType;
      }),
    [entityTypeFilter, l2Mentions, normalizedQuery]
  );

  const filteredSnapshots = useMemo(
    () =>
      l2Snapshots.filter((snapshot) => {
        const matchesQuery =
          normalizedQuery.length === 0 ||
          snapshot.entity_id.toLowerCase().includes(normalizedQuery) ||
          snapshot.current_mood?.toLowerCase().includes(normalizedQuery);
        const matchesType = entityTypeFilter === 'all' || snapshot.entity_type === entityTypeFilter;
        return matchesQuery && matchesType;
      }),
    [entityTypeFilter, l2Snapshots, normalizedQuery]
  );

  const filteredEvents = useMemo(
    () =>
      l1Events.filter((event) => {
        if (normalizedQuery.length === 0) {
          return true;
        }
        return (
          event.raw_content.toLowerCase().includes(normalizedQuery) ||
          event.event_id.toLowerCase().includes(normalizedQuery)
        );
      }),
    [l1Events, normalizedQuery]
  );

  const filteredIdentityLinks = useMemo(
    () =>
      identityLinks.filter((link) => {
        if (visibleEntityIds.size === 0 || normalizedQuery.length === 0) {
          return true;
        }
        return (
          link.runtime_user_id.toLowerCase().includes(normalizedQuery) ||
          link.memory_owner_id.toLowerCase().includes(normalizedQuery)
        );
      }),
    [identityLinks, normalizedQuery, visibleEntityIds.size]
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.knowledge')}
      description={t('memory.pages.knowledge.subtitle')}
      eyebrow={t('memory.pages.knowledge.eyebrow')}
      heroStats={(
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MemoryHeroStat label={t('memory.l2.relationCount')} value={l2Stats.relation_count} tone="accent" />
          <MemoryHeroStat label={t('memory.l2.assertionCount')} value={l2Stats.assertion_count} />
          <MemoryHeroStat label={t('memory.l2.lab.entityCount')} value={l2Entities.length} />
          <MemoryHeroStat label={t('memory.l2.lab.snapshotCount')} value={l2Snapshots.length} />
        </div>
      )}
      heroAside={(
        <div className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[#8e705a]">
            {t('memory.pages.knowledge.focusTitle')}
          </div>
          <div className="text-lg font-semibold text-[#35261c]">
            {entityTypeFilter === 'all' ? t('memory.pages.knowledge.focusAll') : entityTypeFilter}
          </div>
          <p className="leading-6">{t('memory.pages.knowledge.focusBody')}</p>
        </div>
      )}
      actions={
        <Button
          variant="outline"
          className="rounded-2xl border-[#dfc8b5] bg-white/80 hover:bg-white"
          onClick={() => void refresh('l2')}
          disabled={loading || l2ActionLoading}
        >
          {(loading || l2ActionLoading) ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-knowledge-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-knowledge-query"
              className={MEMORY_FILTER_INPUT_CLASS}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('memory.pages.knowledge.searchPlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-knowledge-entity-type">
              {t('memory.filters.entityTypeLabel')}
            </label>
            <select
              id="memory-knowledge-entity-type"
              className={MEMORY_FILTER_SELECT_CLASS}
              value={entityTypeFilter}
              onChange={(event) => setEntityTypeFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              {entityTypes.map((entityType) => (
                <option key={entityType} value={entityType}>
                  {entityType}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    >
      {loading ? (
        <LoadingSpinner />
      ) : (
        <L2Tab
          stats={l2Stats}
          relations={filteredRelations}
          assertions={filteredAssertions}
          identityLinks={filteredIdentityLinks}
          entities={filteredEntities}
          mentions={filteredMentions}
          snapshots={filteredSnapshots}
          conflictRules={l2ConflictRules}
          events={filteredEvents}
          actionLoading={l2ActionLoading}
          onSubmitManualEvent={submitManualL2Event}
          onReplayExtraction={replayL2Extraction}
          onRunReconcile={runL2Reconcile}
          onRunSnapshotRefresh={runL2SnapshotRefresh}
          onUpsertGraphConflictRule={upsertL2GraphConflictRule}
        />
      )}
    </MemoryPageFrame>
  );
};

export default MemoryKnowledgePage;
