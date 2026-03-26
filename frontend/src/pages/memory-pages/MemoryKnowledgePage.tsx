import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { L2Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
} from './MemoryPageFrame';

const KNOWLEDGE_SECTIONS = [
  'overview',
  'knowledgeGraph',
  'theoryOfMind',
  'mindSnapshots',
  'lab',
  'canonicalEntities',
  'recentMentions',
  'conflictRules',
] as const;

type KnowledgeSection = (typeof KNOWLEDGE_SECTIONS)[number];

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
    flushL2Microbatches,
    runL2Reconcile,
    runL2SnapshotRefresh,
    upsertL2GraphConflictRule,
    submitAssertionFeedback,
    refresh,
  } = useMemory({ initialLoadScope: 'l2' });
  const [activeSection, setActiveSection] = useState<KnowledgeSection>('overview');
  const [graphStatusFilter, setGraphStatusFilter] = useState('all');
  const [graphEntityFilter, setGraphEntityFilter] = useState('all');
  const [graphPredicateFilter, setGraphPredicateFilter] = useState('all');

  const graphEntityOptions = useMemo(() => {
    const entityNameById = new Map(
      l2Entities.map((entity) => [entity.entity_id, entity.canonical_name || entity.entity_id] as const)
    );
    return Array.from(
      l2Relations.reduce((map, relation) => {
        map.set(relation.subject_id, entityNameById.get(relation.subject_id) ?? relation.subject_id);
        map.set(relation.object_id, entityNameById.get(relation.object_id) ?? relation.object_id);
        return map;
      }, new Map<string, string>())
    ).sort((left, right) => left[1].localeCompare(right[1]));
  }, [l2Entities, l2Relations]);

  const graphPredicateOptions = useMemo(
    () => Array.from(new Set(l2Relations.map((relation) => relation.predicate).filter(Boolean))).sort(),
    [l2Relations]
  );

  const filteredGraphRelations = useMemo(
    () =>
      l2Relations.filter((relation) => {
        const matchesStatus = graphStatusFilter === 'all' || relation.status === graphStatusFilter;
        const matchesEntity =
          graphEntityFilter === 'all' ||
          relation.subject_id === graphEntityFilter ||
          relation.object_id === graphEntityFilter;
        const matchesPredicate =
          graphPredicateFilter === 'all' || relation.predicate === graphPredicateFilter;
        return matchesStatus && matchesEntity && matchesPredicate;
      }),
    [graphEntityFilter, graphPredicateFilter, graphStatusFilter, l2Relations]
  );

  const dominantPredicates = Array.from(
    l2Relations.reduce((map, relation) => {
      map.set(relation.predicate, (map.get(relation.predicate) ?? 0) + 1);
      return map;
    }, new Map<string, number>())
  ).sort((left, right) => right[1] - left[1]);

  const tabItems = useMemo(
    () =>
      KNOWLEDGE_SECTIONS.map((section) => ({
        value: section,
        label: t(`memory.pages.knowledge.tabs.${section}`),
      })),
    [t]
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.knowledge')}
      description={t('memory.pages.knowledge.subtitle')}
      actions={
        <>
          <Button
            variant="outline"
            className={MEMORY_ACTION_BUTTON_CLASS}
            onClick={() => void flushL2Microbatches()}
            disabled={loading || l2ActionLoading}
          >
            {l2ActionLoading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
            {t('memory.pages.knowledge.actions.flushMicrobatches')}
          </Button>
          <Button
            variant="outline"
            className={MEMORY_ACTION_BUTTON_CLASS}
            onClick={() => void refresh('l2')}
            disabled={loading || l2ActionLoading}
          >
            {(loading || l2ActionLoading) ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
            {t('memory.refresh')}
          </Button>
        </>
      }
    >
      {loading ? (
        <LoadingSpinner />
      ) : (
        <Tabs value={activeSection} onValueChange={(value) => setActiveSection(value as KnowledgeSection)} className="space-y-4">
          <div className="overflow-x-auto pb-1">
            <TabsList
              className="inline-flex h-auto min-w-full justify-start gap-2 rounded-[1.25rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.96)] p-2 shadow-[0_10px_24px_-24px_hsl(var(--memory-shadow)/0.28)]"
              data-testid="memory-knowledge-tablist"
            >
              {tabItems.map((tab) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className="rounded-[0.95rem] border border-transparent px-4 py-2.5 text-sm text-[hsl(var(--memory-body))] data-[state=active]:border-[hsl(var(--memory-border))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))] data-[state=active]:shadow-[0_8px_16px_-18px_hsl(var(--memory-shadow)/0.35)]"
                >
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          {activeSection === 'knowledgeGraph' ? (
            <section
              data-testid="memory-knowledge-graph-filters"
              className="grid gap-3 rounded-[1.25rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.96)] px-5 py-4 md:grid-cols-3"
            >
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-graph-status-filter">
                  {t('memory.pages.knowledge.graphFilters.status')}
                </label>
                <select
                  id="memory-graph-status-filter"
                  className={MEMORY_FILTER_SELECT_CLASS}
                  value={graphStatusFilter}
                  onChange={(event) => setGraphStatusFilter(event.target.value)}
                >
                  <option value="all">{t('memory.l2.lab.relationStatusOptions.all')}</option>
                  <option value="active">{t('memory.l2.lab.relationStatusOptions.active')}</option>
                  <option value="conflicted">{t('memory.l2.lab.relationStatusOptions.conflicted')}</option>
                  <option value="deprecated">{t('memory.l2.lab.relationStatusOptions.deprecated')}</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-graph-entity-filter">
                  {t('memory.pages.knowledge.graphFilters.entity')}
                </label>
                <select
                  id="memory-graph-entity-filter"
                  className={MEMORY_FILTER_SELECT_CLASS}
                  value={graphEntityFilter}
                  onChange={(event) => setGraphEntityFilter(event.target.value)}
                >
                  <option value="all">{t('memory.pages.knowledge.graphFilters.allEntities')}</option>
                  {graphEntityOptions.map(([entityId, label]) => (
                    <option key={entityId} value={entityId}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-graph-predicate-filter">
                  {t('memory.pages.knowledge.graphFilters.predicate')}
                </label>
                <select
                  id="memory-graph-predicate-filter"
                  className={MEMORY_FILTER_SELECT_CLASS}
                  value={graphPredicateFilter}
                  onChange={(event) => setGraphPredicateFilter(event.target.value)}
                >
                  <option value="all">{t('memory.pages.knowledge.graphFilters.allPredicates')}</option>
                  {graphPredicateOptions.map((predicate) => (
                    <option key={predicate} value={predicate}>
                      {predicate}
                    </option>
                  ))}
                </select>
              </div>
            </section>
          ) : null}

          {tabItems.map((tab) => (
            <TabsContent
              key={tab.value}
              value={tab.value}
              className="mt-0"
              data-testid={`memory-knowledge-tab-panel-${tab.value}`}
            >
              <L2Tab
                section={tab.value}
                stats={l2Stats}
                relations={tab.value === 'knowledgeGraph' ? filteredGraphRelations : l2Relations}
                assertions={l2Assertions}
                identityLinks={identityLinks}
                entities={l2Entities}
                mentions={l2Mentions}
                snapshots={l2Snapshots}
                conflictRules={l2ConflictRules}
                events={l1Events}
                dominantPredicates={dominantPredicates}
                actionLoading={l2ActionLoading}
                onSubmitManualEvent={submitManualL2Event}
                onReplayExtraction={replayL2Extraction}
                onRunReconcile={runL2Reconcile}
                onRunSnapshotRefresh={runL2SnapshotRefresh}
                onUpsertGraphConflictRule={upsertL2GraphConflictRule}
                onSubmitAssertionFeedback={submitAssertionFeedback}
              />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryKnowledgePage;
