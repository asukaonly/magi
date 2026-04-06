import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { L1Tab } from '@/components/memory';
import { useMemory } from '@/hooks/useMemory';
import { buildMemorySourceOptions, getMemorySourceLabel } from '@/utils/memory-source-copy';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MemoryWorkspacePanel,
} from './MemoryPageFrame';
import { MemoryPagination, PAGE_SIZE } from './MemoryPagination';

const SUMMARY_PREVIEW_LIMIT = 6;

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

const COMPACT_DATE_INPUT_CLASS =
  'h-9 min-w-0 rounded-none border-0 bg-transparent px-0 text-sm text-[hsl(var(--memory-title))] shadow-none focus-visible:ring-0 focus-visible:ring-offset-0';

const normalizeDateRange = (startDate: string, endDate: string) => {
  const normalizedStartDate = startDate.trim();
  const normalizedEndDate = endDate.trim();

  if (!normalizedStartDate || !normalizedEndDate) {
    return { start: normalizedStartDate || undefined, end: normalizedEndDate || undefined };
  }

  return normalizedStartDate > normalizedEndDate
    ? { start: normalizedEndDate, end: normalizedStartDate }
    : { start: normalizedStartDate, end: normalizedEndDate };
};

export const MemoryEventsPage = () => {
  const { t } = useTranslation('app');
  const { loading, l1Events, l1Total, queryL1Events } = useMemory({ initialLoadScope: 'l1' });
  const [contentQuery, setContentQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [offset, setOffset] = useState(0);
  const [appliedFilters, setAppliedFilters] = useState<
    { query?: string; source?: string; start_date?: string; end_date?: string } | undefined
  >(undefined);

  const sources = useMemo(
    () => Array.from(new Set(l1Events.map((event) => event.source).filter((source): source is string => Boolean(source)))).sort(),
    [l1Events]
  );

  const formatSourceLabel = (source: string) => getMemorySourceLabel(t, source);

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
  const sourceOptions = useMemo(() => buildMemorySourceOptions(t, sources), [sources, t]);

  const buildSearchFilters = () => {
    const { start, end } = normalizeDateRange(startDate, endDate);
    const filters = {
      query: contentQuery.trim() || undefined,
      source: sourceFilter === 'all' ? undefined : sourceFilter,
      start_date: start,
      end_date: end,
    };
    return Object.values(filters).some(Boolean) ? filters : undefined;
  };

  const handleSearch = async () => {
    const filters = buildSearchFilters();
    setAppliedFilters(filters);
    setOffset(0);
    await queryL1Events({ ...filters, offset: 0 });
  };

  const handleReset = async () => {
    setContentQuery('');
    setSourceFilter('all');
    setStartDate('');
    setEndDate('');
    setAppliedFilters(undefined);
    setOffset(0);
    await queryL1Events(undefined);
  };

  const handlePageChange = async (newOffset: number) => {
    setOffset(newOffset);
    await queryL1Events({ ...appliedFilters, offset: newOffset });
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
          className="grid gap-x-3 gap-y-2.5 text-sm lg:grid-cols-[minmax(0,1.52fr)_minmax(340px,1fr)_minmax(140px,0.44fr)_auto] lg:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSearch();
          }}
        >
          <div className="space-y-1">
            <label className="text-[13px] font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-events-content">
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
          <div className="space-y-1">
            <label className="text-[13px] font-medium text-[hsl(var(--memory-title))]" htmlFor="memory-events-start-date">
              {t('memory.pages.events.dateRangeLabel')}
            </label>
            <div className="grid grid-cols-[minmax(0,1fr)_30px_minmax(0,1fr)] items-center rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3">
              <div className="group relative">
                {!startDate ? (
                  <span className="pointer-events-none absolute inset-0 flex items-center bg-[hsl(var(--memory-input-bg))] text-sm text-[hsl(var(--memory-muted))] group-focus-within:hidden">
                    {t('memory.pages.events.startDateLabel')}
                  </span>
                ) : null}
                <Input
                  id="memory-events-start-date"
                  type="date"
                  aria-label={t('memory.pages.events.startDateLabel')}
                  className={COMPACT_DATE_INPUT_CLASS}
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                  autoComplete="off"
                />
              </div>
              <span className="flex h-5 items-center justify-center border-x border-[hsl(var(--memory-divider)/0.62)] text-[12px] text-[hsl(var(--memory-muted))]">
                ~
              </span>
              <div className="group relative">
                {!endDate ? (
                  <span className="pointer-events-none absolute inset-0 flex items-center bg-[hsl(var(--memory-input-bg))] text-sm text-[hsl(var(--memory-muted))] group-focus-within:hidden">
                    {t('memory.pages.events.endDateLabel')}
                  </span>
                ) : null}
                <Input
                  id="memory-events-end-date"
                  type="date"
                  aria-label={t('memory.pages.events.endDateLabel')}
                  className={COMPACT_DATE_INPUT_CLASS}
                  value={endDate}
                  onChange={(event) => setEndDate(event.target.value)}
                  autoComplete="off"
                />
              </div>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-[13px] font-medium text-[hsl(var(--memory-title))]">
              {t('memory.pages.events.sourceFilterLabel')}
            </label>
            <SelectField
              aria-label={t('memory.pages.events.sourceFilterLabel')}
              value={sourceFilter}
              onChange={(value) => setSourceFilter(value || 'all')}
              options={sourceOptions}
              placeholder={t('memory.filters.all')}
              allowEmpty={true}
              triggerClassName="h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] shadow-none focus-visible:ring-[hsl(var(--memory-accent-soft)/0.24)]"
              menuClassName="rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] shadow-[0_10px_20px_rgba(15,23,42,0.06)]"
            />
          </div>
          <div className="flex items-end gap-1.5">
            <Button type="submit" variant="outline" className={MEMORY_ACTION_BUTTON_CLASS} disabled={loading}>
              {t('memory.search')}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="h-9 rounded-sm px-3 text-sm text-[hsl(var(--memory-body))]"
              onClick={() => void handleReset()}
              disabled={loading}
            >
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

          <MemoryPagination
            total={l1Total}
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

export default MemoryEventsPage;
