import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, CalendarDays, ChevronDown, ChevronRight, RefreshCw, Search } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import {
  memoryApi,
  type L1Event,
  type L1EventQueryParams,
  type MemoryDashboard,
  type MemorySourceCount,
} from '@/api/modules/memory';
import {
  sensorsApi,
  type SensorSourceStatusItem,
  type SensorSourceStatusResponse,
  type SensorTodaySummaryResponse,
} from '@/api/modules/sensors';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { cn } from '@/lib/utils';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_SECTION_CARD_CLASS,
} from './MemoryPageFrame';
import {
  formatInteger,
  formatOverviewTimestamp,
  sourceStatusDotClassName,
  sourceStatusLabel,
  type OverviewTranslateFn,
  type SourceCoverageRow,
} from './overview/overviewModel';

interface SourceLedgerRow extends SourceCoverageRow {
  description: string | null;
  supportsPullSync: boolean;
  syncMode: string | null;
  storageMode: string | null;
  nextRunAt: number | string | null;
}

const normalizeSourceKey = (value: string | null | undefined): string => (
  String(value || '').trim().toLowerCase()
);

const sensorLabel = (sensor?: SensorSourceStatusItem | null): string | null => {
  if (!sensor) {
    return null;
  }
  return (
    String(sensor.display_name_translated || '').trim()
    || String(sensor.display_name || '').trim()
    || String(sensor.source_name || '').trim()
    || null
  );
};

const sensorDescription = (sensor?: SensorSourceStatusItem | null): string | null => {
  if (!sensor) {
    return null;
  }
  return (
    String(sensor.description_translated || '').trim()
    || String(sensor.description || '').trim()
    || null
  );
};

const sensorMatchesSource = (
  sensor: SensorSourceStatusItem,
  sourceName: string,
): boolean => {
  const source = normalizeSourceKey(sourceName);
  return [
    sensor.source_name,
    sensor.contribution_id,
    sensor.plugin_id,
  ].map(normalizeSourceKey).includes(source);
};

const findSensorForSource = (
  sourceName: string,
  sensors: SensorSourceStatusItem[],
): SensorSourceStatusItem | undefined => sensors.find((sensor) => sensorMatchesSource(sensor, sourceName));

const rowFromSource = (
  source: MemorySourceCount | null,
  sensor: SensorSourceStatusItem | undefined,
  t: OverviewTranslateFn,
): SourceLedgerRow => {
  const key = source?.source || sensor?.source_name || sensor?.contribution_id || sensor?.plugin_id || '';
  const status = sensor?.status || (sensor ? (sensor.enabled === false ? 'disabled' : 'ready') : 'ready');
  return {
    key,
    label: sensorLabel(sensor) || getMemorySourceLabel(t, key),
    pluginId: sensor?.plugin_id ?? null,
    icon: sensor?.icon ?? null,
    status,
    eventCount: source?.event_count ?? 0,
    lastResultCount: sensor?.last_result_count ?? sensor?.last_raw_result_count ?? null,
    enabled: sensor ? Boolean(sensor.enabled) : null,
    running: sensor?.running == null ? null : Boolean(sensor.running),
    lastSyncAt: sensor?.last_sync_at ?? sensor?.last_run_at ?? null,
    lastEventAt: source?.last_event_at ?? null,
    description: sensorDescription(sensor),
    supportsPullSync: Boolean(sensor?.supports_pull_sync),
    syncMode: sensor?.sync_mode ?? null,
    storageMode: sensor?.storage_mode ?? null,
    nextRunAt: sensor?.next_run_at ?? null,
  };
};

const buildSourceLedgerRows = (
  counts: MemorySourceCount[],
  status: SensorSourceStatusResponse | null,
  t: OverviewTranslateFn,
): SourceLedgerRow[] => {
  const sensors = status?.sources || [];
  const rows = new Map<string, SourceLedgerRow>();

  counts.forEach((source) => {
    const sensor = findSensorForSource(source.source, sensors);
    rows.set(normalizeSourceKey(source.source), rowFromSource(source, sensor, t));
  });

  sensors.forEach((sensor) => {
    const key = normalizeSourceKey(sensor.source_name || sensor.contribution_id || sensor.plugin_id);
    if (!key || rows.has(key)) {
      return;
    }
    rows.set(key, rowFromSource(null, sensor, t));
  });

  return Array.from(rows.values()).sort((left, right) => (
    right.eventCount - left.eventCount
    || Number(Boolean(right.lastResultCount)) - Number(Boolean(left.lastResultCount))
    || left.label.localeCompare(right.label)
  ));
};

const sourceDetailPath = (sourceName: string): string => (
  `/memory/sources/${encodeURIComponent(sourceName)}`
);

const loadSourceOverview = async () => {
  const [dashboardPayload, sensorPayload, todayPayload] = await Promise.all([
    memoryApi.getDashboard({ pending_limit: 8 }),
    sensorsApi.getStatus(),
    sensorsApi.getTodaySummary(),
  ]);
  const todayEventsPayload = await memoryApi.getL1Events({
    start_date: todayPayload.date,
    end_date: todayPayload.date,
    limit: 500,
    offset: 0,
  });
  return {
    dashboard: dashboardPayload,
    sensorStatus: sensorPayload,
    todaySummary: todayPayload,
    todayEvents: todayEventsPayload.items || [],
  };
};

const sourceSyncLabel = (
  row: SourceLedgerRow,
  locale: string,
  t: OverviewTranslateFn,
): string => (
  formatOverviewTimestamp(row.lastSyncAt ?? row.lastEventAt, locale)
  || t('memory.sourcesPage.neverSynced')
);

const sourceResultLabel = (row: SourceLedgerRow, t: OverviewTranslateFn): string => (
  row.lastResultCount == null
    ? t('memory.sourcesPage.noRecentBatch')
    : t('memory.sourcesPage.lastBatch', { count: row.lastResultCount })
);

const PULSE_TIME_LABELS = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '24:00'];
const PULSE_COLORS = ['#2f80d8', '#49b861', '#ef4b3f', '#9061d0', '#f39a2f', '#6f6a63'];
const SOURCE_DETAIL_PAGE_SIZE = 50;

type SourceDetailTimeRange = 'all' | 'today' | 'last7Days' | 'last30Days' | 'custom';
type SourceDetailPresetTimeRange = Exclude<SourceDetailTimeRange, 'custom'>;

const SOURCE_DETAIL_TIME_RANGES: SourceDetailPresetTimeRange[] = ['all', 'today', 'last7Days', 'last30Days'];

interface PulseMark {
  left: number;
  width: number;
  heavy: boolean;
}

const parseDateString = (value: string): Date => {
  const [year, month, day] = value.split('-').map((part) => Number.parseInt(part, 10));
  if (!year || !month || !day) {
    return new Date();
  }
  return new Date(year, month - 1, day);
};

const formatDateString = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const shiftDateString = (value: string, offsetDays: number): string => {
  const date = parseDateString(value);
  date.setDate(date.getDate() + offsetDays);
  return formatDateString(date);
};

const buildSourceDetailEventParams = ({
  sourceName,
  timeRange,
  query,
  anchorDate,
  customStartDate,
  customEndDate,
  offset,
}: {
  sourceName: string;
  timeRange: SourceDetailTimeRange;
  query: string;
  anchorDate: string;
  customStartDate: string;
  customEndDate: string;
  offset: number;
}): L1EventQueryParams => {
  const params: L1EventQueryParams = {
    source: sourceName,
    limit: SOURCE_DETAIL_PAGE_SIZE,
    offset,
  };
  if (timeRange === 'today') {
    params.start_date = anchorDate;
    params.end_date = anchorDate;
  } else if (timeRange === 'last7Days') {
    params.start_date = shiftDateString(anchorDate, -6);
    params.end_date = anchorDate;
  } else if (timeRange === 'last30Days') {
    params.start_date = shiftDateString(anchorDate, -29);
    params.end_date = anchorDate;
  } else if (timeRange === 'custom') {
    if (customStartDate) {
      params.start_date = customStartDate;
    }
    if (customEndDate) {
      params.end_date = customEndDate;
    }
  }
  const normalizedQuery = query.trim();
  if (normalizedQuery) {
    params.query = normalizedQuery;
  }
  return params;
};

const getTodayCountMap = (todaySummary: SensorTodaySummaryResponse | null): Map<string, number> => {
  const counts = new Map<string, number>();
  (todaySummary?.sources || []).forEach((source) => {
    counts.set(normalizeSourceKey(source.source_name), Math.max(0, Number(source.count || 0)));
  });
  return counts;
};

const dayBoundsFromSummary = (todaySummary: SensorTodaySummaryResponse | null): { start: number; end: number } => {
  const date = todaySummary?.date || new Date().toISOString().slice(0, 10);
  const startMs = new Date(`${date}T00:00:00`).getTime();
  const start = Number.isFinite(startMs) ? startMs / 1000 : new Date().setHours(0, 0, 0, 0) / 1000;
  return { start, end: start + 24 * 60 * 60 };
};

const buildPulseMarks = (
  events: L1Event[],
  dayStart: number,
  dayEnd: number,
): PulseMark[] => {
  if (events.length === 0 || dayEnd <= dayStart) {
    return [];
  }
  const sorted = [...events]
    .map((event) => Number(event.timestamp || 0))
    .filter((timestamp) => Number.isFinite(timestamp) && timestamp >= dayStart && timestamp <= dayEnd)
    .sort((left, right) => left - right);
  if (sorted.length === 0) {
    return [];
  }

  const groups: number[][] = [];
  const mergeWindowSeconds = 45 * 60;
  sorted.forEach((timestamp) => {
    const current = groups[groups.length - 1];
    if (!current || timestamp - current[current.length - 1] > mergeWindowSeconds) {
      groups.push([timestamp]);
      return;
    }
    current.push(timestamp);
  });

  const dayLength = dayEnd - dayStart;
  return groups.map((group) => {
    const first = group[0];
    const last = group[group.length - 1];
    const left = ((first - dayStart) / dayLength) * 100;
    const durationWidth = ((last - first) / dayLength) * 100;
    const countWidth = group.length > 1 ? 1.8 + group.length * 0.65 : 0.7;
    return {
      left: Math.max(0, Math.min(left, 98)),
      width: Math.min(Math.max(durationWidth, countWidth), 12),
      heavy: group.length > 1,
    };
  });
};

function SourceIcon({
  row,
  className,
  iconClassName,
}: {
  row: SourceLedgerRow;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <span className={cn(
      'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.72)]',
      className
    )}>
      <PluginIcon
        iconId={row.icon}
        pluginId={row.pluginId}
        sourceName={row.key}
        className={cn('h-6 w-6 text-[hsl(var(--memory-body))]', iconClassName)}
      />
    </span>
  );
}

function MemorySourcesLoading() {
  const { t } = useTranslation('app');
  return (
    <section className={MEMORY_EMPTY_PANEL_CLASS}>
      <div className="flex items-center gap-2">
        <LoadingSpinner className="h-4 w-4" />
        <span>{t('memory.sourcesPage.loading')}</span>
      </div>
    </section>
  );
}

function MemorySourcesError() {
  const { t } = useTranslation('app');
  return <section className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.sourcesPage.error')}</section>;
}

function SourcePulseSection({
  rows,
  dashboard,
  todaySummary,
  todayEvents,
}: {
  rows: SourceLedgerRow[];
  dashboard: MemoryDashboard | null;
  todaySummary: SensorTodaySummaryResponse | null;
  todayEvents: L1Event[];
}) {
  const { t } = useTranslation('app');
  const todayCounts = getTodayCountMap(todaySummary);
  const todaySourceByKey = new Map(
    (todaySummary?.sources || []).map((source) => [normalizeSourceKey(source.source_name), source])
  );
  const pulseRows = rows
    .filter((row) => (todayCounts.get(normalizeSourceKey(row.key)) || 0) > 0)
    .slice(0, 5);
  const eventGroups = todayEvents.reduce((groups, event) => {
    const source = normalizeSourceKey(event.source);
    if (!source) {
      return groups;
    }
    const items = groups.get(source) || [];
    items.push(event);
    groups.set(source, items);
    return groups;
  }, new Map<string, L1Event[]>());
  const dayBounds = dayBoundsFromSummary(todaySummary);
  const todayCount = todaySummary
    ? Array.from(todayCounts.values()).reduce((sum, count) => sum + count, 0)
    : dashboard?.deltas?.today?.l1_events ?? 0;
  const backlogCount = dashboard?.processing_backlog?.total_pending ?? 0;
  const errorCount = rows.filter((row) => row.status === 'error').length;

  return (
    <section className={cn(MEMORY_SECTION_CARD_CLASS, 'px-5 py-5')}>
      <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 space-y-1.5">
          <h1 className="text-[1.55rem] font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.sourcesPage.sections.pulse')}
          </h1>
          <p className="max-w-2xl text-sm leading-6 text-[hsl(var(--memory-body))]">
            {t('memory.sourcesPage.pulseSubtitle')}
          </p>
        </div>

        <div className="flex flex-wrap items-start gap-5 xl:justify-end">
          <div className="flex flex-wrap items-start gap-5 rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.22)] px-4 py-3">
            <div className="min-w-[88px]">
              <div className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.pulseStats.today')}</div>
              <div className="mt-1 text-2xl font-semibold text-[hsl(var(--memory-title))]">{formatInteger(todayCount)}</div>
            </div>
            <div className="h-12 w-px bg-[hsl(var(--memory-divider)/0.72)]" aria-hidden="true" />
            <div className="min-w-[88px]">
              <div className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.pulseStats.backlog')}</div>
              <div className="mt-1 text-2xl font-semibold text-[hsl(var(--memory-title))]">{formatInteger(backlogCount)}</div>
            </div>
            <div className="h-12 w-px bg-[hsl(var(--memory-divider)/0.72)]" aria-hidden="true" />
            <div className="min-w-[72px]">
              <div className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.pulseStats.errors')}</div>
              <div className={cn(
                'mt-1 text-2xl font-semibold',
                errorCount > 0 ? 'text-red-600' : 'text-[hsl(var(--memory-title))]'
              )}>
                {formatInteger(errorCount)}
              </div>
            </div>
          </div>
        </div>
      </div>

      {pulseRows.length > 0 ? (
        <div className="mt-7 overflow-x-auto pb-1">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[180px_minmax(0,1fr)] gap-x-6">
              <div />
              <div className="flex justify-between px-1 text-xs font-medium text-[hsl(var(--memory-muted))]">
                {PULSE_TIME_LABELS.map((label) => (
                  <span key={label}>{label}</span>
                ))}
              </div>
            </div>

            <div className="mt-4 space-y-4">
              {pulseRows.map((row, index) => {
                const sourceKey = normalizeSourceKey(row.key);
                const color = row.status === 'error' ? '#ef3b2d' : PULSE_COLORS[index % PULSE_COLORS.length];
                const sourceEvents = eventGroups.get(sourceKey) || [];
                const fallbackEventAt = todaySourceByKey.get(sourceKey)?.last_event_at;
                const marks = buildPulseMarks(
                  sourceEvents.length > 0 || fallbackEventAt == null
                    ? sourceEvents
                    : [{
                        event_id: `${row.key}:last-event`,
                        event_type: 'SENSOR_EVENT',
                        source: row.key,
                        timestamp: fallbackEventAt,
                        content: '',
                        memory_domain: 'activity',
                        retention_class: 'normal',
                        importance_score: 0,
                        cognition_eligible: true,
                      }],
                  dayBounds.start,
                  dayBounds.end,
                );
                return (
                  <div
                    key={row.key}
                    data-testid={`source-pulse-row-${row.key}`}
                    className="grid grid-cols-[180px_minmax(0,1fr)] gap-x-6"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full shadow-[0_0_0_3px_hsl(var(--memory-panel-subtle)/0.7)]"
                        style={{ backgroundColor: color }}
                        aria-hidden="true"
                      />
                      <span className="truncate text-base font-medium text-[hsl(var(--memory-title))]">{row.label}</span>
                    </div>

                    <div className="relative h-8">
                      <div className="absolute inset-0 flex justify-between" aria-hidden="true">
                        {PULSE_TIME_LABELS.map((label) => (
                          <span key={label} className="h-full w-px bg-[hsl(var(--memory-divider)/0.58)]" />
                        ))}
                      </div>
                      <div className="absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 bg-[hsl(var(--memory-divider)/0.48)]" aria-hidden="true" />
                      {marks.length > 0 ? (
                        marks.map((mark, markIndex) => (
                          <span
                            key={`${row.key}-${markIndex}`}
                            className="absolute top-1/2 -translate-y-1/2 rounded-full"
                            style={{
                              left: `${mark.left}%`,
                              width: mark.heavy ? `${mark.width}%` : '8px',
                              height: '8px',
                              backgroundColor: color,
                              opacity: mark.heavy ? 0.68 : 0.82,
                            }}
                            aria-hidden="true"
                          />
                        ))
                      ) : (
                        <span
                          className="absolute left-0 right-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-[hsl(var(--memory-panel-subtle)/0.62)]"
                          aria-hidden="true"
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        <div className={cn(MEMORY_EMPTY_PANEL_CLASS, 'mt-5')}>{t('memory.sourcesPage.empty')}</div>
      )}
    </section>
  );
}

function SourceLedgerSection({
  rows,
  todaySummary,
}: {
  rows: SourceLedgerRow[];
  todaySummary: SensorTodaySummaryResponse | null;
}) {
  const { t, i18n } = useTranslation('app');
  const todayCounts = getTodayCountMap(todaySummary);

  return (
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.sourcesPage.sections.ledger')}
          </h2>
          <p className="text-sm leading-6 text-[hsl(var(--memory-body))]">
            {t('memory.sourcesPage.ledgerSubtitle')}
          </p>
        </div>
        <span className="rounded-full bg-[hsl(var(--memory-panel-subtle)/0.76)] px-3 py-1 text-xs text-[hsl(var(--memory-muted))]">
          {t('memory.sourcesPage.localOnly')}
        </span>
      </div>

      <div className="mt-4 divide-y divide-[hsl(var(--memory-divider)/0.58)]">
        {rows.length > 0 ? (
          <>
            <div className="hidden grid-cols-[minmax(0,1.35fr)_120px_150px_110px_110px_76px] gap-3 pb-2 text-xs text-[hsl(var(--memory-muted))] lg:grid">
              <div>{t('memory.sourcesPage.columns.source')}</div>
              <div>{t('memory.sourcesPage.columns.status')}</div>
              <div>{t('memory.sourcesPage.columns.lastSync')}</div>
              <div>{t('memory.sourcesPage.columns.today')}</div>
              <div>{t('memory.sourcesPage.columns.stored')}</div>
              <div className="text-right">{t('memory.sourcesPage.columns.action')}</div>
            </div>
            {rows.map((row) => {
              const statusLabel = sourceStatusLabel(row.status, t);
              const syncLabel = sourceSyncLabel(row, i18n.language, t);
              return (
                <div
                  key={row.key}
                  className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1.35fr)_120px_150px_110px_110px_76px] lg:items-center"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <SourceIcon row={row} />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-[hsl(var(--memory-title))]">{row.label}</div>
                      <div className="truncate text-xs text-[hsl(var(--memory-muted))]">
                        {row.description || t('memory.sourcesPage.descriptionFallback')}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-[hsl(var(--memory-body))]">
                    <span className={`h-2 w-2 rounded-full ${sourceStatusDotClassName(row.status)}`} aria-hidden="true" />
                    <span>{statusLabel}</span>
                  </div>
                  <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                    <div>{syncLabel}</div>
                    <div>{sourceResultLabel(row, t)}</div>
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                      {formatInteger(todayCounts.get(normalizeSourceKey(row.key)) || 0)}
                    </div>
                    <div className="text-xs text-[hsl(var(--memory-muted))] lg:hidden">{t('memory.sourcesPage.columns.today')}</div>
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{formatInteger(row.eventCount)}</div>
                    <div className="text-xs text-[hsl(var(--memory-muted))] lg:hidden">{t('memory.sourcesPage.columns.stored')}</div>
                  </div>
                  <div className="flex justify-start lg:justify-end">
                    <Link
                      to={sourceDetailPath(row.key)}
                      className="inline-flex h-8 items-center gap-1 rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 text-xs font-medium text-[hsl(var(--memory-title))] transition-colors hover:bg-[hsl(var(--memory-panel-subtle)/0.82)]"
                    >
                      {t('memory.sourcesPage.actions.view')}
                      <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                    </Link>
                  </div>
                </div>
              );
            })}
          </>
        ) : (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.sourcesPage.empty')}</div>
        )}
      </div>
    </section>
  );
}

export const MemorySourcesPage = () => {
  const { t } = useTranslation('app');
  const [dashboard, setDashboard] = useState<MemoryDashboard | null>(null);
  const [sensorStatus, setSensorStatus] = useState<SensorSourceStatusResponse | null>(null);
  const [todaySummary, setTodaySummary] = useState<SensorTodaySummaryResponse | null>(null);
  const [todayEvents, setTodayEvents] = useState<L1Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const payload = await loadSourceOverview();
        if (cancelled) {
          return;
        }
        setDashboard(payload.dashboard);
        setSensorStatus(payload.sensorStatus);
        setTodaySummary(payload.todaySummary);
        setTodayEvents(payload.todayEvents);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo(
    () => buildSourceLedgerRows(dashboard?.source_counts || [], sensorStatus, t),
    [dashboard?.source_counts, sensorStatus, t],
  );

  return (
    <MemoryPageFrame title={t('memory.sourcesPage.title')} description={t('memory.sourcesPage.subtitle')} hideHeader>
      {loading ? (
        <MemorySourcesLoading />
      ) : error ? (
        <MemorySourcesError />
      ) : (
        <div className="space-y-4">
          <SourcePulseSection
            rows={rows}
            dashboard={dashboard}
            todaySummary={todaySummary}
            todayEvents={todayEvents}
          />
          <SourceLedgerSection rows={rows} todaySummary={todaySummary} />
        </div>
      )}
    </MemoryPageFrame>
  );
};

const fallbackSourceRow = (sourceName: string, t: OverviewTranslateFn): SourceLedgerRow => ({
  key: sourceName,
  label: getMemorySourceLabel(t, sourceName),
  pluginId: null,
  icon: null,
  status: 'ready',
  eventCount: 0,
  lastResultCount: null,
  enabled: null,
  running: null,
  lastSyncAt: null,
  lastEventAt: null,
  description: null,
  supportsPullSync: false,
  syncMode: null,
  storageMode: null,
  nextRunAt: null,
});

function SourceDetailHeader({
  row,
  syncing,
  onSync,
}: {
  row: SourceLedgerRow;
  syncing: boolean;
  onSync: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const statusLabel = sourceStatusLabel(row.status, t);
  return (
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <Link
        to="/memory/sources"
        className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-[hsl(var(--memory-muted))] transition-colors hover:text-[hsl(var(--memory-title))]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        {t('memory.sourcesPage.actions.back')}
      </Link>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 gap-4">
          <SourceIcon row={row} className="h-16 w-16 rounded-xl" iconClassName="h-8 w-8" />
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[1.75rem] font-semibold text-[hsl(var(--memory-title))]">{row.label}</h1>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--memory-panel-subtle)/0.72)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]">
                <span className={`h-2 w-2 rounded-full ${sourceStatusDotClassName(row.status)}`} aria-hidden="true" />
                {statusLabel}
              </span>
            </div>
            <p className="max-w-3xl text-sm leading-6 text-[hsl(var(--memory-body))]">
              {row.description || t('memory.sourcesPage.descriptionFallback')}
            </p>
            <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
              <span>{t('memory.sourcesPage.localOnly')}</span>
              <span className="text-[hsl(var(--memory-divider))]">/</span>
              <span>{t('memory.sourcesPage.detail.lastSync', { value: sourceSyncLabel(row, i18n.language, t) })}</span>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">
          <button
            type="button"
            className={cn(MEMORY_ACTION_BUTTON_CLASS, 'inline-flex items-center gap-2', syncing && 'opacity-70')}
            onClick={onSync}
            disabled={syncing || !row.supportsPullSync}
          >
            {syncing ? <LoadingSpinner className="h-3.5 w-3.5" /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
            {t('memory.sourcesPage.actions.sync')}
          </button>
          <button type="button" className={MEMORY_ACTION_BUTTON_CLASS}>
            {t('memory.sourcesPage.actions.settings')}
          </button>
          <button type="button" className={MEMORY_ACTION_BUTTON_CLASS}>
            {t('memory.sourcesPage.actions.pause')}
          </button>
        </div>
      </div>
    </section>
  );
}

function SourceDetailStats({ row, todayCount }: { row: SourceLedgerRow; todayCount: number }) {
  const { t, i18n } = useTranslation('app');
  const stats = [
    { label: t('memory.sourcesPage.columns.stored'), value: formatInteger(row.eventCount) },
    { label: t('memory.sourcesPage.columns.today'), value: formatInteger(todayCount) },
    { label: t('memory.sourcesPage.detail.nextRun'), value: formatOverviewTimestamp(row.nextRunAt, i18n.language) || t('memory.sourcesPage.notScheduled') },
    { label: t('memory.sourcesPage.detail.syncMode'), value: row.syncMode || t('memory.sourcesPage.unknown') },
  ];
  return (
    <section className="grid gap-3 md:grid-cols-4">
      {stats.map((stat) => (
        <div key={stat.label} className="rounded-lg border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-4 py-3">
          <div className="text-xs text-[hsl(var(--memory-muted))]">{stat.label}</div>
          <div className="mt-1.5 truncate text-lg font-semibold text-[hsl(var(--memory-title))]">{stat.value}</div>
        </div>
      ))}
    </section>
  );
}

function SourceRecentEvents({
  events,
  total,
  loading,
  loadingMore,
  hasMore,
  timeRange,
  customStartDate,
  customEndDate,
  queryDraft,
  onTimeRangeChange,
  onApplyCustomRange,
  onQueryDraftChange,
  onSearch,
  onLoadMore,
}: {
  events: L1Event[];
  total: number;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  timeRange: SourceDetailTimeRange;
  customStartDate: string;
  customEndDate: string;
  queryDraft: string;
  onTimeRangeChange: (value: SourceDetailTimeRange) => void;
  onApplyCustomRange: (startDate: string, endDate: string) => void;
  onQueryDraftChange: (value: string) => void;
  onSearch: () => void;
  onLoadMore: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const [timePickerOpen, setTimePickerOpen] = useState(false);
  const [draftCustomStartDate, setDraftCustomStartDate] = useState(customStartDate);
  const [draftCustomEndDate, setDraftCustomEndDate] = useState(customEndDate);

  const timeRangeLabel = (value: SourceDetailTimeRange): string => {
    if (value === 'custom') {
      return t('memory.sourcesPage.detail.timeRange.custom');
    }
    if (value === 'today') {
      return t('memory.sourcesPage.detail.timeRange.today');
    }
    if (value === 'last7Days') {
      return t('memory.sourcesPage.detail.timeRange.last7Days');
    }
    if (value === 'last30Days') {
      return t('memory.sourcesPage.detail.timeRange.last30Days');
    }
    return t('memory.sourcesPage.detail.timeRange.all');
  };
  const selectedTimeRangeLabel = () => {
    if (timeRange !== 'custom') {
      return timeRangeLabel(timeRange);
    }
    if (customStartDate && customEndDate) {
      return `${customStartDate} - ${customEndDate}`;
    }
    return customStartDate || customEndDate || timeRangeLabel('custom');
  };
  const handleTimePickerOpenChange = (open: boolean) => {
    if (open) {
      setDraftCustomStartDate(customStartDate);
      setDraftCustomEndDate(customEndDate);
    }
    setTimePickerOpen(open);
  };
  const selectPresetTimeRange = (value: SourceDetailPresetTimeRange) => {
    onTimeRangeChange(value);
    setTimePickerOpen(false);
  };
  const applyCustomRange = () => {
    onApplyCustomRange(draftCustomStartDate, draftCustomEndDate);
    setTimePickerOpen(false);
  };
  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSearch();
  };
  return (
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.sourcesPage.detail.recentTitle')}
        </h2>
        <span className="text-xs text-[hsl(var(--memory-muted))]">
          {t('memory.sourcesPage.detail.recentCountDetailed', {
            total: formatInteger(total),
            shown: formatInteger(events.length),
          })}
        </span>
      </div>
      <form className="mt-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between" onSubmit={submitSearch}>
        <Popover open={timePickerOpen} onOpenChange={handleTimePickerOpenChange}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className={cn(
                MEMORY_ACTION_BUTTON_CLASS,
                'inline-flex w-fit min-w-[10rem] items-center justify-between gap-2 px-3'
              )}
            >
              <span className="inline-flex min-w-0 items-center gap-2">
                <CalendarDays className="h-3.5 w-3.5 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
                <span className="truncate">{selectedTimeRangeLabel()}</span>
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            className="w-[280px] border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-panel-elevated))] p-2 text-[hsl(var(--memory-title))] shadow-[0_18px_36px_rgba(15,23,42,0.08)]"
          >
            <div className="grid gap-1">
              {SOURCE_DETAIL_TIME_RANGES.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={cn(
                    'flex h-9 items-center justify-between rounded-sm px-3 text-sm transition-colors',
                    timeRange === value
                      ? 'bg-[hsl(var(--memory-panel-subtle)/0.76)] text-[hsl(var(--memory-title))]'
                      : 'text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-subtle)/0.56)]'
                  )}
                  onClick={() => selectPresetTimeRange(value)}
                >
                  {timeRangeLabel(value)}
                  {timeRange === value ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--memory-accent))]" aria-hidden="true" />
                  ) : null}
                </button>
              ))}
            </div>
            <div className="my-2 h-px bg-[hsl(var(--memory-divider)/0.56)]" />
            <div className="grid gap-2 px-1 pb-1">
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="date"
                  aria-label={t('memory.sourcesPage.detail.customStart')}
                  value={draftCustomStartDate}
                  onChange={(event) => setDraftCustomStartDate(event.target.value)}
                  className={cn(MEMORY_FILTER_INPUT_CLASS, 'w-full border px-2 text-xs')}
                />
                <input
                  type="date"
                  aria-label={t('memory.sourcesPage.detail.customEnd')}
                  value={draftCustomEndDate}
                  onChange={(event) => setDraftCustomEndDate(event.target.value)}
                  className={cn(MEMORY_FILTER_INPUT_CLASS, 'w-full border px-2 text-xs')}
                />
              </div>
              <button
                type="button"
                className={cn(
                  MEMORY_ACTION_BUTTON_CLASS,
                  'inline-flex w-full items-center justify-center',
                  !draftCustomStartDate && !draftCustomEndDate ? 'opacity-50' : ''
                )}
                onClick={applyCustomRange}
                disabled={!draftCustomStartDate && !draftCustomEndDate}
              >
                {t('memory.sourcesPage.detail.applyCustomRange')}
              </button>
            </div>
          </PopoverContent>
        </Popover>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative min-w-0 sm:w-[260px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[hsl(var(--memory-muted))]" aria-hidden="true" />
            <input
              value={queryDraft}
              onChange={(event) => onQueryDraftChange(event.target.value)}
              placeholder={t('memory.sourcesPage.detail.searchPlaceholder')}
              className="h-9 w-full rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] pl-9 pr-3 text-sm text-[hsl(var(--memory-title))] outline-none transition-colors placeholder:text-[hsl(var(--memory-muted))] focus:border-[hsl(var(--memory-accent)/0.55)]"
            />
          </div>
          <button
            type="submit"
            className={cn(MEMORY_ACTION_BUTTON_CLASS, 'inline-flex items-center justify-center gap-2')}
          >
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
            {t('memory.sourcesPage.detail.searchAction')}
          </button>
        </div>
      </form>
      <div className="mt-4 divide-y divide-[hsl(var(--memory-divider)/0.58)]">
        {loading ? (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>
            <div className="flex items-center gap-2">
              <LoadingSpinner className="h-4 w-4" />
              <span>{t('memory.sourcesPage.detail.eventsLoading')}</span>
            </div>
          </div>
        ) : events.length > 0 ? (
          events.map((event) => (
            <article key={event.event_id} className="grid gap-2 py-3 md:grid-cols-[160px_minmax(0,1fr)_110px] md:items-start">
              <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                {formatOverviewTimestamp(event.timestamp, i18n.language) || t('memory.sourcesPage.unknownTime')}
              </div>
              <div className="min-w-0">
                <div className="line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-title))]">{event.content}</div>
              </div>
              <div className="text-xs text-[hsl(var(--memory-muted))] md:text-right">
                {t('memory.sourcesPage.detail.stored')}
              </div>
            </article>
          ))
        ) : (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.sourcesPage.detail.eventsEmpty')}</div>
        )}
      </div>
      {!loading && hasMore ? (
        <div className="mt-4 flex justify-center">
          <button
            type="button"
            className={cn(MEMORY_ACTION_BUTTON_CLASS, 'inline-flex items-center gap-2')}
            onClick={onLoadMore}
            disabled={loadingMore}
          >
            {loadingMore ? <LoadingSpinner className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5 rotate-90" aria-hidden="true" />}
            {loadingMore ? t('memory.sourcesPage.detail.loadingMore') : t('memory.sourcesPage.detail.loadMore')}
          </button>
        </div>
      ) : null}
    </section>
  );
}

export const MemorySourceDetailPage = () => {
  const params = useParams();
  const { t } = useTranslation('app');
  const sourceName = decodeURIComponent(params.sourceName || '');
  const [dashboard, setDashboard] = useState<MemoryDashboard | null>(null);
  const [sensorStatus, setSensorStatus] = useState<SensorSourceStatusResponse | null>(null);
  const [todaySummary, setTodaySummary] = useState<SensorTodaySummaryResponse | null>(null);
  const [events, setEvents] = useState<L1Event[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [metadataReady, setMetadataReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [timeRange, setTimeRange] = useState<SourceDetailTimeRange>('all');
  const [customDateRange, setCustomDateRange] = useState({ start: '', end: '' });
  const [queryDraft, setQueryDraft] = useState('');
  const [query, setQuery] = useState('');

  const loadMetadata = async (cancelledRef?: { cancelled: boolean }) => {
    setLoading(true);
    setMetadataReady(false);
    setError(null);
    try {
      const [dashboardPayload, sensorPayload, todayPayload] = await Promise.all([
        memoryApi.getDashboard({ pending_limit: 8 }),
        sensorsApi.getStatus(),
        sensorsApi.getTodaySummary(),
      ]);
      if (cancelledRef?.cancelled) {
        return;
      }
      setDashboard(dashboardPayload);
      setSensorStatus(sensorPayload);
      setTodaySummary(todayPayload);
      setMetadataReady(true);
    } catch (err) {
      if (!cancelledRef?.cancelled) {
        setError(err instanceof Error ? err.message : String(err));
        setMetadataReady(false);
      }
    } finally {
      if (!cancelledRef?.cancelled) {
        setLoading(false);
      }
    }
  };

  const loadEvents = async (options?: {
    offset?: number;
    append?: boolean;
    cancelledRef?: { cancelled: boolean };
  }) => {
    const offset = options?.offset ?? 0;
    const append = Boolean(options?.append);
    if (append) {
      setLoadingMore(true);
    } else {
      setEventsLoading(true);
    }
    setError(null);
    try {
      const eventsPayload = await memoryApi.getL1Events(buildSourceDetailEventParams({
        sourceName,
        timeRange,
        query,
        anchorDate: todaySummary?.date || formatDateString(new Date()),
        customStartDate: customDateRange.start,
        customEndDate: customDateRange.end,
        offset,
      }));
      if (options?.cancelledRef?.cancelled) {
        return;
      }
      const nextEvents = eventsPayload.items || [];
      setEvents((current) => (append ? [...current, ...nextEvents] : nextEvents));
      setEventsTotal(eventsPayload.total ?? nextEvents.length);
    } catch (err) {
      if (!options?.cancelledRef?.cancelled) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (!options?.cancelledRef?.cancelled) {
        if (append) {
          setLoadingMore(false);
        } else {
          setEventsLoading(false);
        }
      }
    }
  };

  useEffect(() => {
    const cancelledRef = { cancelled: false };
    void loadMetadata(cancelledRef);
    return () => {
      cancelledRef.cancelled = true;
    };
  }, [sourceName]);

  useEffect(() => {
    if (!metadataReady) {
      return undefined;
    }
    const cancelledRef = { cancelled: false };
    void loadEvents({ cancelledRef });
    return () => {
      cancelledRef.cancelled = true;
    };
  }, [metadataReady, sourceName, timeRange, customDateRange.start, customDateRange.end, query, todaySummary?.date]);

  const rows = useMemo(
    () => buildSourceLedgerRows(dashboard?.source_counts || [], sensorStatus, t),
    [dashboard?.source_counts, sensorStatus, t],
  );
  const row = rows.find((item) => normalizeSourceKey(item.key) === normalizeSourceKey(sourceName))
    || fallbackSourceRow(sourceName, t);
  const todayCount = getTodayCountMap(todaySummary).get(normalizeSourceKey(row.key)) || 0;
  const hasMore = events.length < eventsTotal;

  const handleSync = async () => {
    setSyncing(true);
    try {
      await sensorsApi.requestSync(sourceName);
      await loadMetadata();
    } finally {
      setSyncing(false);
    }
  };

  const handleSearch = () => {
    setQuery(queryDraft.trim());
  };

  const handleApplyCustomRange = (startDate: string, endDate: string) => {
    setCustomDateRange({ start: startDate, end: endDate });
    setTimeRange('custom');
  };

  const handleLoadMore = () => {
    void loadEvents({ offset: events.length, append: true });
  };

  return (
    <MemoryPageFrame title={row.label} description={t('memory.sourcesPage.subtitle')} hideHeader>
      {loading && !dashboard ? (
        <MemorySourcesLoading />
      ) : error ? (
        <MemorySourcesError />
      ) : (
        <div className="space-y-4">
          <SourceDetailHeader row={row} syncing={syncing} onSync={handleSync} />
          <SourceDetailStats row={row} todayCount={todayCount} />
          <SourceRecentEvents
            events={events}
            total={eventsTotal}
            loading={eventsLoading}
            loadingMore={loadingMore}
            hasMore={hasMore}
            timeRange={timeRange}
            customStartDate={customDateRange.start}
            customEndDate={customDateRange.end}
            queryDraft={queryDraft}
            onTimeRangeChange={setTimeRange}
            onApplyCustomRange={handleApplyCustomRange}
            onQueryDraftChange={setQueryDraft}
            onSearch={handleSearch}
            onLoadMore={handleLoadMore}
          />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemorySourcesPage;
