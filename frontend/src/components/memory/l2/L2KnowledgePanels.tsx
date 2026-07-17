import React from 'react';
import type { L1Event } from '@/api/modules/memory';
import {
  ENTITY_KNOWLEDGE_PREVIEW_LIMIT,
  formatEventTime,
  type EntityOverviewItem,
  type KnowledgeBaseGroup,
  type KnowledgeBaseGroupId,
  type KnowledgeCorrectionAction,
  type KnowledgeItem,
  type MemoryTranslateFn,
} from '../l2KnowledgeModel';
import { EmptyState, SummaryPill } from './L2Primitives';
import { KnowledgeItemRow } from './L2KnowledgeItemRow';

export const KnowledgeListPanel: React.FC<{
  title: string;
  emptyText: string;
  items: KnowledgeItem[];
  count?: number;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}> = ({ title, emptyText, items, count, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onRequestAssertionCorrection, t }) => (
  <section className="overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
      <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
      <span className="text-xs text-[hsl(var(--memory-muted))]">{count ?? items.length}</span>
    </div>
    {items.length === 0 ? (
      <div className="px-4 py-4">
        <EmptyState copy={emptyText} />
      </div>
    ) : (
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.52)]">
        {items.map((item) => (
          <KnowledgeItemRow
            key={item.id}
            item={item}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onRequestAssertionCorrection={onRequestAssertionCorrection}
            t={t}
          />
        ))}
      </div>
    )}
  </section>
);

export const KnowledgeBaseBrowser: React.FC<{
  groups: KnowledgeBaseGroup[];
  selectedGroupId: KnowledgeBaseGroupId;
  selectedGroup: KnowledgeBaseGroup | undefined;
  reviewItems: KnowledgeItem[];
  stableItems: KnowledgeItem[];
  relationItems: KnowledgeItem[];
  deprecatedItems: KnowledgeItem[];
  emptyText: string;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  onSelectGroup: (groupId: KnowledgeBaseGroupId) => void;
  t: MemoryTranslateFn;
}> = ({
  groups,
  selectedGroupId,
  selectedGroup,
  reviewItems,
  stableItems,
  relationItems,
  deprecatedItems,
  emptyText,
  actionLoading,
  evidenceEventsById,
  loadingEvidenceIds,
  onLoadEvidenceEvents,
  onSubmitAssertionFeedback,
  onRequestAssertionCorrection,
  onSelectGroup,
  t,
}) => {
  const hasItems = Boolean(selectedGroup && selectedGroup.totalCount > 0);

  return (
    <section className="grid gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <aside className="min-w-0 rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)]">
        <div className="border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
          <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{t('memory.pages.knowledge.sections.knowledgeDirectory')}</h2>
        </div>
        <div className="space-y-1 p-2">
          {groups.map((group) => {
            const isSelected = group.id === selectedGroupId;
            return (
              <button
                key={group.id}
                type="button"
                className={`w-full rounded-sm border px-3 py-2 text-left transition-colors ${isSelected
                  ? 'border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel))] text-[hsl(var(--memory-title))]'
                  : 'border-transparent text-[hsl(var(--memory-body))] hover:border-[hsl(var(--memory-border)/0.5)] hover:bg-[hsl(var(--memory-panel-subtle)/0.38)]'}`}
                onClick={() => onSelectGroup(group.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{group.label}</span>
                  <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{group.totalCount}</span>
                </div>
                <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] leading-5 text-[hsl(var(--memory-muted))]">
                  <span>{t('memory.pages.knowledge.groupCounts.stable', { count: group.counts.stable })}</span>
                  <span>{t('memory.pages.knowledge.groupCounts.review', { count: group.counts.review })}</span>
                  <span>{t('memory.pages.knowledge.groupCounts.relations', { count: group.counts.relations })}</span>
                  <span>{t('memory.pages.knowledge.groupCounts.deprecated', { count: group.counts.deprecated })}</span>
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="min-w-0 overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
        <div className="border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{selectedGroup?.label ?? t('memory.pages.knowledge.groups.all')}</h2>
            {selectedGroup ? (
              <span className="text-xs text-[hsl(var(--memory-muted))]">
                {t('memory.pages.knowledge.knowledgeBaseSummary', {
                  total: selectedGroup.totalCount,
                  stable: selectedGroup.counts.stable,
                  review: selectedGroup.counts.review,
                  relations: selectedGroup.counts.relations,
                  deprecated: selectedGroup.counts.deprecated,
                })}
              </span>
            ) : null}
          </div>
        </div>

        {!hasItems ? (
          <div className="px-4 py-4">
            <EmptyState copy={emptyText} />
          </div>
        ) : (
          <div className="space-y-3 p-3">
            {reviewItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.pendingSignals')}
                items={reviewItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onRequestAssertionCorrection={onRequestAssertionCorrection}
                t={t}
              />
            ) : null}
            {stableItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.stableKnowledge')}
                items={stableItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onRequestAssertionCorrection={onRequestAssertionCorrection}
                t={t}
              />
            ) : null}
            {relationItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.relations')}
                items={relationItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onRequestAssertionCorrection={onRequestAssertionCorrection}
                t={t}
              />
            ) : null}
            {deprecatedItems.length > 0 ? (
              <KnowledgeGroupItemSection
                title={t('memory.pages.knowledge.sections.deprecatedKnowledge')}
                items={deprecatedItems}
                actionLoading={actionLoading}
                evidenceEventsById={evidenceEventsById}
                loadingEvidenceIds={loadingEvidenceIds}
                onLoadEvidenceEvents={onLoadEvidenceEvents}
                onSubmitAssertionFeedback={onSubmitAssertionFeedback}
                onRequestAssertionCorrection={onRequestAssertionCorrection}
                t={t}
              />
            ) : null}
          </div>
        )}
      </section>
    </section>
  );
};

const KnowledgeGroupItemSection: React.FC<{
  title: string;
  items: KnowledgeItem[];
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  t: MemoryTranslateFn;
}> = ({ title, items, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onRequestAssertionCorrection, t }) => (
  <section className="min-w-0 overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel)/0.58)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.46)] px-3 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
      <span>{title}</span>
      <span className="shrink-0">{t('memory.pages.knowledge.totalItemCount', { total: items.length })}</span>
    </div>
    <div className="max-h-[42rem] divide-y divide-[hsl(var(--memory-divider)/0.46)] overflow-y-auto overscroll-contain">
      {items.map((item) => (
        <KnowledgeItemRow
          key={`${title}-${item.id}`}
          item={item}
          actionLoading={actionLoading}
          evidenceEventsById={evidenceEventsById}
          loadingEvidenceIds={loadingEvidenceIds}
          onLoadEvidenceEvents={onLoadEvidenceEvents}
          onSubmitAssertionFeedback={onSubmitAssertionFeedback}
          onRequestAssertionCorrection={onRequestAssertionCorrection}
          t={t}
        />
      ))}
    </div>
  </section>
);

export const EntityOverviewPanel: React.FC<{
  title: string;
  emptyText: string;
  items: EntityOverviewItem[];
  count?: number;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  t: MemoryTranslateFn;
}> = ({ title, emptyText, items, count, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onRequestAssertionCorrection, t }) => (
  <section className="overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
      <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
      <span className="text-xs text-[hsl(var(--memory-muted))]">{count ?? items.length}</span>
    </div>
    {items.length === 0 ? (
      <div className="px-4 py-4">
        <EmptyState copy={emptyText} />
      </div>
    ) : (
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.52)]">
        {items.map((item) => (
          <EntityOverviewRow
            key={item.id}
            item={item}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onRequestAssertionCorrection={onRequestAssertionCorrection}
            t={t}
          />
        ))}
      </div>
    )}
  </section>
);

const EntityOverviewRow: React.FC<{
  item: EntityOverviewItem;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  t: MemoryTranslateFn;
}> = ({ item, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onRequestAssertionCorrection, t }) => {
  const metrics = [
    t('memory.pages.knowledge.entityMetrics.stableKnowledge', { count: item.knowledgeCount }),
    t('memory.pages.knowledge.entityMetrics.pendingSignals', { count: item.reviewCount }),
    t('memory.pages.knowledge.entityMetrics.relations', { count: item.relationCount }),
    t('memory.pages.knowledge.entityMetrics.assertions', { count: item.assertionCount }),
  ];
  const summary = item.summary.length > 0
    ? item.summary.slice(0, 4).join(' · ')
    : t('memory.pages.knowledge.entitySummaryFallback', {
      stable: item.knowledgeCount,
      relations: item.relationCount,
      assertions: item.assertionCount,
    });
  const lastUpdated = formatEventTime(item.lastUpdatedAt);

  return (
    <details className="group">
      <summary className="cursor-pointer list-none px-4 py-3 transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.38)] [&::-webkit-details-marker]:hidden">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-sm font-semibold leading-6 text-[hsl(var(--memory-title))]">{item.name}</span>
            </div>
            <div className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{summary}</div>
            {lastUpdated ? (
              <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                {t('memory.pages.knowledge.fields.updatedAt')}: {lastUpdated}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap justify-start gap-1.5 md:justify-end">
            {metrics.map((metric) => (
              <SummaryPill key={`${item.id}-${metric}`}>{metric}</SummaryPill>
            ))}
          </div>
        </div>
      </summary>
      <div className="border-t border-[hsl(var(--memory-divider)/0.52)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3">
        <div className="space-y-3">
          <EntityKnowledgeMiniList
            title={t('memory.pages.knowledge.sections.stableKnowledge')}
            emptyText={t('memory.pages.knowledge.emptyStableKnowledge')}
            items={item.activeItems.slice(0, ENTITY_KNOWLEDGE_PREVIEW_LIMIT)}
            totalCount={item.activeItems.length}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onRequestAssertionCorrection={onRequestAssertionCorrection}
            t={t}
          />
          <EntityKnowledgeMiniList
            title={t('memory.pages.knowledge.sections.pendingSignals')}
            emptyText={t('memory.pages.knowledge.emptyPendingSignals')}
            items={item.reviewItems.slice(0, ENTITY_KNOWLEDGE_PREVIEW_LIMIT)}
            totalCount={item.reviewItems.length}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onRequestAssertionCorrection={onRequestAssertionCorrection}
            t={t}
          />
        </div>
      </div>
    </details>
  );
};

const EntityKnowledgeMiniList: React.FC<{
  title: string;
  emptyText: string;
  items: KnowledgeItem[];
  totalCount: number;
  actionLoading: boolean;
  evidenceEventsById: Map<string, L1Event | null>;
  loadingEvidenceIds: Record<string, boolean>;
  onLoadEvidenceEvents: (eventIds: string[]) => Promise<void>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (item: KnowledgeItem, action: KnowledgeCorrectionAction) => void;
  t: MemoryTranslateFn;
}> = ({ title, emptyText, items, totalCount, actionLoading, evidenceEventsById, loadingEvidenceIds, onLoadEvidenceEvents, onSubmitAssertionFeedback, onRequestAssertionCorrection, t }) => (
  <section className="min-w-0 overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel)/0.58)]">
    <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.46)] px-3 py-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
      <span>{title}</span>
      <span className="shrink-0">
        {items.length < totalCount
          ? t('memory.pages.knowledge.visibleItemCount', { shown: items.length, total: totalCount })
          : t('memory.pages.knowledge.totalItemCount', { total: totalCount })}
      </span>
    </div>
    {items.length === 0 ? (
      <div className="px-3 py-3 text-sm leading-6 text-[hsl(var(--memory-muted))]">{emptyText}</div>
    ) : (
      <div className="max-h-[32rem] divide-y divide-[hsl(var(--memory-divider)/0.46)] overflow-y-auto overscroll-contain">
        {items.map((knowledgeItem) => (
          <KnowledgeItemRow
            key={`${title}-${knowledgeItem.id}`}
            item={knowledgeItem}
            actionLoading={actionLoading}
            evidenceEventsById={evidenceEventsById}
            loadingEvidenceIds={loadingEvidenceIds}
            onLoadEvidenceEvents={onLoadEvidenceEvents}
            onSubmitAssertionFeedback={onSubmitAssertionFeedback}
            onRequestAssertionCorrection={onRequestAssertionCorrection}
            t={t}
          />
        ))}
      </div>
    )}
  </section>
);
