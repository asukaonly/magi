import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L3Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame from './MemoryPageFrame';

export const MemoryReflectionPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l3Summaries, refresh } = useMemory();
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');

  const summaryTypes = useMemo(
    () => Array.from(new Set(l3Summaries.map((summary) => summary.summary_type).filter(Boolean))).sort(),
    [l3Summaries]
  );

  const filteredSummaries = useMemo(
    () =>
      l3Summaries.filter((summary) => {
        const normalizedQuery = query.trim().toLowerCase();
        const matchesQuery =
          normalizedQuery.length === 0 ||
          summary.content.toLowerCase().includes(normalizedQuery) ||
          summary.summary_category.toLowerCase().includes(normalizedQuery);
        const matchesType = typeFilter === 'all' || summary.summary_type === typeFilter;
        return matchesQuery && matchesType;
      }),
    [l3Summaries, query, typeFilter]
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.reflection')}
      description={t('memory.pages.reflection.subtitle')}
      actions={
        <Button variant="outline" onClick={() => void refresh('l3')} disabled={loading}>
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-reflection-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-reflection-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('memory.pages.reflection.searchPlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-reflection-type">
              {t('memory.filters.typeLabel')}
            </label>
            <select
              id="memory-reflection-type"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              {summaryTypes.map((summaryType) => (
                <option key={summaryType} value={summaryType}>
                  {summaryType}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    >
      {loading ? <LoadingSpinner /> : <L3Tab stats={stats.l3} summaries={filteredSummaries} />}
    </MemoryPageFrame>
  );
};

export default MemoryReflectionPage;
