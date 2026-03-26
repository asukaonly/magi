import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { L1Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';

const SUMMARY_PREVIEW_LIMIT = 6;
const SOURCE_LABEL_KEYS: Record<string, string> = {
  chat_projector: 'memory.sources.chat_projector',
  runtime_action_emitter: 'memory.sources.runtime_action_emitter',
  timeline_importer: 'memory.sources.timeline_importer',
  manual_journal: 'memory.sources.manual_journal',
  l2_lab: 'memory.sources.l2_lab',
};

const buildSummaryText = (items: Array<[string, number]>, emptyLabel: string) => {
  if (items.length === 0) {
    return { full: emptyLabel, preview: emptyLabel };
  }
  const segments = items.map(([label, count]) => `${label} · ${count}`);
  return {
    full: segments.join(' / '),
    preview: [...segments.slice(0, SUMMARY_PREVIEW_LIMIT), ...(segments.length > SUMMARY_PREVIEW_LIMIT ? ['...'] : [])].join(' / '),
  };
};

export const MemoryEventsPage = () => {
  const { t } = useTranslation('app');
  const { loading, l1Events, queryL1Events } = useMemory({ initialLoadScope: 'l1' });
  const [contentQuery, setContentQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [appliedFilters, setAppliedFilters] = useState<
    { query?: string; source?: string; start_date?: string; end_date?: string } | undefined
  >(undefined);

  const sources = useMemo(
    () => Array.from(new Set(l1Events.map((event) => event.source).filter((source): source is string => Boolean(source)))).sort(),
    [l1Events]
  );

  const formatSourceLabel = (source: string) => {
    const key = SOURCE_LABEL_KEYS[source];
    if (!key) {
      return source;
    }
    const translated = t(key);
    return translated === key ? source : translated;
  };

  const domainCounts = Array.from(
    l1Events.reduce((map, event) => {
      const key = event.memory_domain || 'general';
      map.set(key, (map.get(key) ?? 0) + 1);
      return map;
    }, new Map<string, number>())
  ).sort((left, right) => right[1] - left[1]);
  const sourceCounts = Array.from(
    l1Events.reduce((map, event) => {
      const key = event.source || 'unknown';
      map.set(key, (map.get(key) ?? 0) + 1);
      return map;
    }, new Map<string, number>())
  ).sort((left, right) => right[1] - left[1]);
  const localizedSourceCounts = sourceCounts.map(([source, count]) => [formatSourceLabel(source), count] as [string, number]);
  const sourceSummary = buildSummaryText(localizedSourceCounts, t('memory.filters.all'));
  const domainSummary = buildSummaryText(domainCounts, t('memory.filters.all'));

  const buildSearchFilters = () => {
    const normalizedStartDate = startDate.trim();
    const normalizedEndDate = endDate.trim();
    const start = normalizedStartDate && normalizedEndDate && normalizedStartDate > normalizedEndDate
      ? normalizedEndDate
      : normalizedStartDate;
    const end = normalizedStartDate && normalizedEndDate && normalizedStartDate > normalizedEndDate
      ? normalizedStartDate
      : normalizedEndDate;
    const filters = {
      query: contentQuery.trim() || undefined,
      source: sourceFilter === 'all' ? undefined : sourceFilter,
      start_date: start || undefined,
      end_date: end || undefined,
    };
    return Object.values(filters).some(Boolean) ? filters : undefined;
  };

  const handleSearch = async () => {
    const filters = buildSearchFilters();
    setAppliedFilters(filters);
    await queryL1Events(filters);
  };

  const handleReset = async () => {
    setContentQuery('');
    setSourceFilter('all');
    setStartDate('');
    setEndDate('');
    setAppliedFilters(undefined);
    await queryL1Events(undefined);
  };

  return (
    <MemoryPageFrame
      title={t('memory.nav.events')}
      description={t('memory.pages.events.subtitle')}
      actions={
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          onClick={() => void queryL1Events(appliedFilters)}
          disabled={loading}
        >
          {loading ? <LoadingSpinner className="mr-2 h-4 w-4" /> : null}
          {t('memory.refresh')}
        </Button>
      }
      filters={(
        <form
          className="grid gap-x-4 gap-y-3 lg:grid-cols-[minmax(0,1.18fr)_minmax(340px,0.98fr)_minmax(240px,0.82fr)_auto] lg:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSearch();
          }}
        >
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-events-content">
              {t('memory.pages.events.contentLabel')}
            </label>
            <Input
              id="memory-events-content"
              className={MEMORY_FILTER_INPUT_CLASS}
              value={contentQuery}
              onChange={(event) => setContentQuery(event.target.value)}
              placeholder={t('memory.pages.events.searchPlaceholder')}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-events-start-date">
              {t('memory.pages.events.dateRangeLabel')}
            </label>
            <div className="grid grid-cols-[minmax(0,1fr)_12px_minmax(0,1fr)] items-center gap-2">
              <Input
                id="memory-events-start-date"
                type="date"
                aria-label={t('memory.pages.events.startDateLabel')}
                className={`${MEMORY_FILTER_INPUT_CLASS} min-w-0`}
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
              <span className="text-center text-sm text-[hsl(var(--memory-muted))]">~</span>
              <Input
                id="memory-events-end-date"
                type="date"
                aria-label={t('memory.pages.events.endDateLabel')}
                className={`${MEMORY_FILTER_INPUT_CLASS} min-w-0`}
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="memory-events-source">
              {t('memory.pages.events.sourceFilterLabel')}
            </label>
            <select
              id="memory-events-source"
              aria-label={t('memory.pages.events.sourceFilterLabel')}
              className={MEMORY_FILTER_SELECT_CLASS}
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value)}
            >
              <option value="all">{t('memory.filters.all')}</option>
              {sources.map((source) => (
                <option key={source} value={source}>
                  {formatSourceLabel(source)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <Button type="submit" variant="outline" className={MEMORY_ACTION_BUTTON_CLASS} disabled={loading}>
              {t('memory.search')}
            </Button>
            <Button type="button" variant="ghost" className="rounded-md px-4" onClick={() => void handleReset()} disabled={loading}>
              {t('memory.pages.events.resetButton')}
            </Button>
          </div>
        </form>
      )}
    >
      {loading ? <LoadingSpinner /> : (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            <MemoryWorkspacePanel
              testId="memory-events-source-summary"
              title={t('memory.pages.events.sourceSummaryTitle')}
            >
              <p
                className="min-h-[3.5rem] text-sm leading-7 text-[hsl(var(--memory-body))] line-clamp-2"
                title={sourceSummary.full}
              >
                {sourceSummary.preview}
              </p>
            </MemoryWorkspacePanel>

            <MemoryWorkspacePanel
              title={t('memory.pages.events.domainSummaryTitle')}
            >
              <p
                className="min-h-[3.5rem] text-sm leading-7 text-[hsl(var(--memory-body))] line-clamp-2"
                title={domainSummary.full}
              >
                {domainSummary.preview}
              </p>
            </MemoryWorkspacePanel>
          </div>

          <L1Tab
            stats={{ event_count: l1Events.length }}
            events={l1Events}
            showStats={false}
            formatSourceLabel={formatSourceLabel}
          />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEventsPage;
