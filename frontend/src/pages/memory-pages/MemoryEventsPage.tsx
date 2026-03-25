import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L1Tab } from '@/components/memory';
import { formatTimestamp } from '@/hooks/useMemory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_INFO_PANEL_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MemoryTag,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

export const MemoryEventsPage = () => {
  const { t } = useTranslation('app');
  const { loading, stats, l1Events, refresh } = useMemory({ initialLoadScope: 'l1' });
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
          event.content.toLowerCase().includes(normalizedQuery) ||
          event.event_type.toLowerCase().includes(normalizedQuery) ||
          event.memory_domain.toLowerCase().includes(normalizedQuery);
        const matchesSource = sourceFilter === 'all' || event.source === sourceFilter;
        return matchesQuery && matchesSource;
      }),
    [l1Events, query, sourceFilter]
  );

  const domainCounts = Array.from(
    filteredEvents.reduce((map, event) => {
      const key = event.memory_domain || 'general';
      map.set(key, (map.get(key) ?? 0) + 1);
      return map;
    }, new Map<string, number>())
  ).sort((left, right) => right[1] - left[1]);
  const latestEvent = filteredEvents[0] ?? null;

  return (
    <MemoryPageFrame
      title={t('memory.nav.events')}
      description={t('memory.pages.events.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
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
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <MemoryWorkspacePanel
              testId="memory-events-source-summary"
              title={t('memory.pages.events.sourceSummaryTitle')}
              description={t('memory.pages.events.sourceSummaryBody')}
            >
              <div className="flex flex-wrap gap-2">
                {sources.map((source) => (
                  <MemoryTag key={source}>
                    {source} · {filteredEvents.filter((event) => event.source === source).length}
                  </MemoryTag>
                ))}
                {sources.length === 0 ? <MemoryTag>{t('memory.filters.all')}</MemoryTag> : null}
              </div>
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.events.domainSummaryTitle')}
              description={t('memory.pages.events.domainSummaryBody')}
            >
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  {domainCounts.slice(0, 5).map(([domain, count]) => (
                    <MemoryTag key={domain}>{domain} · {count}</MemoryTag>
                  ))}
                  {domainCounts.length === 0 ? <MemoryTag>{t('memory.filters.all')}</MemoryTag> : null}
                </div>
                {latestEvent ? (
                  <div className={MEMORY_INFO_PANEL_CLASS}>
                    {t('memory.pages.events.latestEventLabel', { time: formatTimestamp(latestEvent.timestamp) })}
                  </div>
                ) : null}
              </div>
            </MemoryWorkspacePanel>
          </div>

          <L1Tab stats={stats.l1} events={filteredEvents} />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEventsPage;
