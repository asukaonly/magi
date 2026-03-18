import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L1Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame from './MemoryPageFrame';

export const MemoryEventsPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l1Events, refresh } = useMemory();
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');

  const sources = useMemo(
    () => Array.from(new Set(l1Events.map((event) => event.source).filter(Boolean))).sort(),
    [l1Events]
  );

  const filteredEvents = useMemo(
    () =>
      l1Events.filter((event) => {
        const normalizedQuery = query.trim().toLowerCase();
        const matchesQuery =
          normalizedQuery.length === 0 ||
          event.raw_content.toLowerCase().includes(normalizedQuery) ||
          event.event_type.toLowerCase().includes(normalizedQuery) ||
          event.memory_domain.toLowerCase().includes(normalizedQuery);
        const matchesSource = sourceFilter === 'all' || event.source === sourceFilter;
        return matchesQuery && matchesSource;
      }),
    [l1Events, query, sourceFilter]
  );

  return (
    <MemoryPageFrame
      title={t('memory.nav.events')}
      description={t('memory.pages.events.subtitle')}
      actions={
        <Button variant="outline" onClick={() => void refresh('l1')} disabled={loading}>
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-events-query">
              {t('memory.filters.searchLabel')}
            </label>
            <Input
              id="memory-events-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('memory.pages.events.searchPlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-events-source">
              {t('memory.filters.sourceLabel')}
            </label>
            <select
              id="memory-events-source"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              {sources.map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    >
      {loading ? <LoadingSpinner /> : <L1Tab stats={stats.l1} events={filteredEvents} />}
    </MemoryPageFrame>
  );
};

export default MemoryEventsPage;
