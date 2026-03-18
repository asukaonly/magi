import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L1Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, { MEMORY_FILTER_INPUT_CLASS, MEMORY_FILTER_SELECT_CLASS, MemoryHeroStat } from './MemoryPageFrame';

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

  const userAuthoredCount = filteredEvents.filter((event) => event.source === 'user').length;

  return (
    <MemoryPageFrame
      title={t('memory.nav.events')}
      description={t('memory.pages.events.subtitle')}
      eyebrow={t('memory.pages.events.eyebrow')}
      heroStats={(
        <div className="grid gap-3 sm:grid-cols-3">
          <MemoryHeroStat label={t('memory.l1.totalEvents')} value={stats.l1.event_count} tone="accent" />
          <MemoryHeroStat label={t('memory.l1.userAuthored')} value={userAuthoredCount} />
          <MemoryHeroStat label={t('memory.filters.sourceLabel')} value={sources.length} />
        </div>
      )}
      heroAside={(
        <div className="space-y-3">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-[#8e705a]">
            {t('memory.pages.events.focusTitle')}
          </div>
          <div className="text-lg font-semibold text-[#35261c]">{t('memory.pages.events.focusHeadline')}</div>
          <p className="leading-6">{t('memory.pages.events.focusBody')}</p>
        </div>
      )}
      actions={
        <Button
          variant="outline"
          className="rounded-2xl border-[#dfc8b5] bg-white/80 hover:bg-white"
          onClick={() => void refresh('l1')}
          disabled={loading}
        >
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
              className={MEMORY_FILTER_INPUT_CLASS}
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
              className={MEMORY_FILTER_SELECT_CLASS}
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
