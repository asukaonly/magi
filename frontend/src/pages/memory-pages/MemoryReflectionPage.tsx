import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L3Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
} from './MemoryPageFrame';
import { MemoryPagination, PAGE_SIZE } from './MemoryPagination';

export const MemoryReflectionPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l3Summaries, l3Total, loadL3Summaries, refresh } = useMemory({ initialLoadScope: 'l3' });
  const [queryDraft, setQueryDraft] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);

  const handlePageChange = async (newOffset: number) => {
    setOffset(newOffset);
    await loadL3Summaries({ offset: newOffset });
  };

  const filteredSummaries = useMemo(
    () =>
      l3Summaries.filter((summary) => {
        const normalizedQuery = query.trim().toLowerCase();
        const topicMatches = summary.key_topics.some((topic) => topic.toLowerCase().includes(normalizedQuery));
        const entityMatches = (summary.key_entities || []).some((entity) =>
          [entity.entity_id, entity.entity_type].some((value) =>
            typeof value === 'string' && value.toLowerCase().includes(normalizedQuery)
          )
        );
        const matchesQuery =
          normalizedQuery.length === 0 ||
          summary.content.toLowerCase().includes(normalizedQuery) ||
          summary.summary_category.toLowerCase().includes(normalizedQuery) ||
          summary.summary_type.toLowerCase().includes(normalizedQuery) ||
          topicMatches ||
          entityMatches;
        return matchesQuery;
      }),
    [l3Summaries, query]
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.reflection')}
      description={t('memory.pages.reflection.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          onClick={() => void refresh('l3')}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <form
          className="grid gap-x-3 gap-y-2.5 text-sm lg:grid-cols-[minmax(0,1fr)_auto_auto] lg:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            setQuery(queryDraft);
          }}
        >
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-reflection-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-reflection-query"
              className={MEMORY_FILTER_INPUT_CLASS}
              value={queryDraft}
              onChange={(event) => setQueryDraft(event.target.value)}
              placeholder={t('memory.pages.reflection.searchPlaceholder')}
            />
          </div>
          <Button type="submit" variant="outline" className={MEMORY_ACTION_BUTTON_CLASS} disabled={loading}>
            {t('memory.search')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="h-9 rounded-sm px-3 text-sm text-[hsl(var(--memory-body))]"
            onClick={() => {
              setQueryDraft('');
              setQuery('');
            }}
            disabled={loading}
          >
            {t('memory.pages.events.resetButton')}
          </Button>
        </form>
      )}
    >
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <L3Tab stats={stats.l3} summaries={filteredSummaries} />
          <MemoryPagination
            total={l3Total}
            offset={offset}
            limit={PAGE_SIZE}
            loading={loading}
            onPageChange={(newOffset) => void handlePageChange(newOffset)}
          />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryReflectionPage;
