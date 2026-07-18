import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { L2Tab } from '@/components/memory';
import MemoryCorrectionDialog from '@/components/memory/correction/MemoryCorrectionDialog';
import type { MemoryCorrectionUiTarget } from '@/components/memory/correction/memoryCorrectionModel';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
} from './MemoryPageFrame';

const KNOWLEDGE_SECTIONS = [
  'overview',
  'knowledgeBase',
  'advanced',
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
  const [knowledgeQuery, setKnowledgeQuery] = useState('');
  const [knowledgeStatusFilter, setKnowledgeStatusFilter] = useState('all');
  const [knowledgeEntityTypeFilter, setKnowledgeEntityTypeFilter] = useState('all');
  const [correctionTarget, setCorrectionTarget] = useState<MemoryCorrectionUiTarget | null>(null);
  const [correctionAction, setCorrectionAction] = useState<'replace' | 'remove'>('replace');

  const entityTypeOptions = useMemo(
    () => Array.from(new Set([
      ...l2Entities.map((entity) => entity.entity_type),
      ...l2Relations.flatMap((relation) => [relation.subject_type, relation.object_type]),
      ...l2Assertions.map((assertion) => assertion.entity_type),
      ...l2Mentions.map((mention) => mention.entity_type).filter((value): value is string => Boolean(value)),
      ...l2Snapshots.map((snapshot) => snapshot.entity_type),
    ].filter(Boolean))).sort(),
    [l2Assertions, l2Entities, l2Mentions, l2Relations, l2Snapshots]
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
      title={t('memory.nav.dev.knowledge')}
      description={t('memory.pages.knowledge.subtitle')}
      actions={
        <>
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
              className="inline-flex h-auto min-w-full justify-start gap-1 rounded-sm border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.86)] p-1"
              data-testid="memory-knowledge-tablist"
            >
              {tabItems.map((tab) => (
                <TabsTrigger
                  key={tab.value}
                  value={tab.value}
                  className="rounded-sm border border-transparent px-4 py-2 text-sm text-[hsl(var(--memory-body))] data-[state=active]:border-[hsl(var(--memory-border))] data-[state=active]:bg-[hsl(var(--memory-panel))] data-[state=active]:text-[hsl(var(--memory-title))]"
                >
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          {activeSection === 'knowledgeBase' ? (
            <section
              data-testid="memory-knowledge-filters"
              className="grid gap-3 rounded-sm border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.78)] px-4 py-3 md:grid-cols-[minmax(0,1.4fr)_minmax(150px,0.45fr)_minmax(180px,0.55fr)]"
            >
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-knowledge-search">
                  {t('memory.filters.searchLabel')}
                </label>
                <Input
                  id="memory-knowledge-search"
                  className="h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 text-sm text-[hsl(var(--memory-title))] shadow-none focus-visible:ring-[hsl(var(--memory-accent-soft)/0.24)]"
                  value={knowledgeQuery}
                  onChange={(event) => setKnowledgeQuery(event.target.value)}
                  placeholder={t('memory.pages.knowledge.searchPlaceholder')}
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-knowledge-status-filter">
                  {t('memory.filters.statusLabel')}
                </label>
                <select
                  id="memory-knowledge-status-filter"
                  className={MEMORY_FILTER_SELECT_CLASS}
                  value={knowledgeStatusFilter}
                  onChange={(event) => setKnowledgeStatusFilter(event.target.value)}
                >
                  <option value="all">{t('memory.pages.knowledge.statusOptions.all')}</option>
                  <option value="needsReview">{t('memory.pages.knowledge.statusOptions.needsReview')}</option>
                  <option value="active">{t('memory.pages.knowledge.statusOptions.active')}</option>
                  <option value="conflicted">{t('memory.pages.knowledge.statusOptions.conflicted')}</option>
                  <option value="deprecated">{t('memory.pages.knowledge.statusOptions.deprecated')}</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-knowledge-entity-type-filter">
                  {t('memory.filters.entityTypeLabel')}
                </label>
                <select
                  id="memory-knowledge-entity-type-filter"
                  className={MEMORY_FILTER_SELECT_CLASS}
                  value={knowledgeEntityTypeFilter}
                  onChange={(event) => setKnowledgeEntityTypeFilter(event.target.value)}
                >
                  <option value="all">{t('memory.pages.knowledge.entityTypeAll')}</option>
                  {entityTypeOptions.map((entityType) => (
                    <option key={entityType} value={entityType}>
                      {entityType}
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
                relations={l2Relations}
                assertions={l2Assertions}
                identityLinks={identityLinks}
                entities={l2Entities}
                mentions={l2Mentions}
                snapshots={l2Snapshots}
                conflictRules={l2ConflictRules}
                events={l1Events}
                dominantPredicates={dominantPredicates}
                knowledgeQuery={knowledgeQuery}
                knowledgeStatusFilter={knowledgeStatusFilter}
                knowledgeEntityTypeFilter={knowledgeEntityTypeFilter}
                actionLoading={l2ActionLoading}
                onFlushMicrobatches={flushL2Microbatches}
                onSubmitManualEvent={submitManualL2Event}
                onReplayExtraction={replayL2Extraction}
                onRunReconcile={runL2Reconcile}
                onRunSnapshotRefresh={runL2SnapshotRefresh}
                onUpsertGraphConflictRule={upsertL2GraphConflictRule}
                onSubmitAssertionFeedback={submitAssertionFeedback}
                onRequestAssertionCorrection={(item, action) => {
                  if (!item.assertionId || item.correctionValue === undefined) return;
                  setCorrectionAction(action);
                  setCorrectionTarget({
                    kind: 'assertion',
                    id: item.assertionId,
                    displaySentence: item.title,
                    editableValue: item.correctionValue,
                    expectedUpdatedAt: item.expectedUpdatedAt ?? undefined,
                  });
                }}
              />
            </TabsContent>
          ))}
        </Tabs>
      )}
      <MemoryCorrectionDialog
        open={correctionTarget !== null}
        target={correctionTarget}
        initialRecordErrorAction={correctionAction}
        onOpenChange={(open) => {
          if (!open) setCorrectionTarget(null);
        }}
        onSaved={() => refresh('l2')}
        onConflict={() => refresh('l2')}
      />
    </MemoryPageFrame>
  );
};

export default MemoryKnowledgePage;
