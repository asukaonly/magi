import { useMemo, type ComponentProps, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import type { KnowledgePageState, MemoryKnowledgePages } from '@/hooks/useMemoryKnowledge';
import { buildKnowledgeItems, type MemoryTranslateFn } from '../l2KnowledgeModel';
import { getReadableEntityType } from '../l2KnowledgeModelHelpers';
import { KnowledgeItemRow } from './L2KnowledgeItemRow';

type RowActions = Omit<ComponentProps<typeof KnowledgeItemRow>, 'item'>;
type PageStatus = Omit<KnowledgePageState<unknown>, 'items'>;

function PageSection({ title, page, children, t, hint }: {
  title: string;
  page: PageStatus;
  children: ReactNode;
  t: MemoryTranslateFn;
  hint?: string;
}) {
  return (
    <section aria-label={title} className="overflow-hidden rounded-sm border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.64)]">
      <div className="flex items-center justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
        <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
        {page.total !== null ? <span className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.pages.knowledge.pagination.total', { count: page.total })}</span> : null}
      </div>
      {hint ? <p className="px-4 pt-3 text-xs text-[hsl(var(--memory-muted))]">{hint}</p> : null}
      {page.loading ? (
        <div className="flex items-center gap-2 p-4" role="status"><LoadingSpinner className="h-4 w-4" />{t('memory.pages.knowledge.pagination.loading')}</div>
      ) : (
        <>
          {children}
          {page.total === 0 && !page.error ? <p className="p-4 text-sm text-[hsl(var(--memory-muted))]">{t('memory.pages.knowledge.emptyKnowledge')}</p> : null}
        </>
      )}
      {page.error ? (
        <div role="alert" className="flex items-center justify-between gap-3 p-4 text-sm">
          <span>{t('memory.pages.knowledge.pagination.error')}</span>
          <Button variant="outline" onClick={() => void page.retry()}>{t('memory.pages.knowledge.pagination.retry')}</Button>
        </div>
      ) : null}
    </section>
  );
}

function LoadMore({ page, count, t }: { page: PageStatus; count: number; t: MemoryTranslateFn }) {
  if (page.loading || page.error || page.total === null || count >= page.total) return null;
  return (
    <div className="flex items-center justify-between gap-3 border-t border-[hsl(var(--memory-divider)/0.5)] px-4 py-3">
      <span className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.pages.knowledge.pagination.loaded', { count, total: page.total })}</span>
      <Button variant="outline" disabled={page.loadingMore} onClick={() => void page.loadMore()}>
        {page.loadingMore ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
        {t('memory.pages.knowledge.pagination.loadMore')}
      </Button>
    </div>
  );
}

export function L2PagedKnowledgeBrowser({ pages, selfEntityAliases, ...rowActions }: RowActions & {
  pages: MemoryKnowledgePages;
  selfEntityAliases: Set<string>;
}) {
  const { t } = rowActions;
  const entityById = useMemo(() => new Map(pages.entities.items.map(entity => [entity.entity_id, entity])), [pages.entities.items]);
  const items = useMemo(() => buildKnowledgeItems({
    relations: pages.relations.items, assertions: pages.assertions.items, entityById, selfEntityAliases, t,
  }), [entityById, pages.assertions.items, pages.relations.items, selfEntityAliases, t]);
  return (
    <div className="space-y-4">
      {(['assertions', 'relations'] as const).map(kind => (
        <PageSection key={kind} title={t(`memory.pages.knowledge.pagination.${kind}`)} page={pages[kind]} t={t}>
          <div className="divide-y divide-[hsl(var(--memory-divider)/0.52)]">
            {items.filter(item => item.kind === (kind === 'assertions' ? 'assertion' : 'relation')).map(item => (
              <KnowledgeItemRow key={item.id} item={item} {...rowActions} />
            ))}
          </div>
          <LoadMore page={pages[kind]} count={pages[kind].items.length} t={t} />
        </PageSection>
      ))}
      <PageSection title={t('memory.pages.knowledge.pagination.entities')} page={pages.entities} t={t} hint={t('memory.pages.knowledge.pagination.entitiesHint')}>
        <ul className="divide-y divide-[hsl(var(--memory-divider)/0.52)]">
          {pages.entities.items.map(entity => (
            <li key={entity.entity_id} className="px-4 py-3">
              <div className="flex items-baseline justify-between gap-3"><span className="break-words text-sm font-medium text-[hsl(var(--memory-title))]">{entity.canonical_name}</span><span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{getReadableEntityType(t, entity.entity_type)}</span></div>
              {entity.aliases.length > 0 ? <p className="mt-1 break-words text-xs text-[hsl(var(--memory-muted))]">{entity.aliases.join(' · ')}</p> : null}
            </li>
          ))}
        </ul>
        <LoadMore page={pages.entities} count={pages.entities.items.length} t={t} />
      </PageSection>
    </div>
  );
}
