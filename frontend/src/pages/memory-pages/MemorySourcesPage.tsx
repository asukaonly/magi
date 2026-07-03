import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { memoryApi, type L1Event, type MemoryDashboard, type MemorySourceCount } from '@/api/modules/memory';
import { sensorsApi, type SensorSourceStatusItem, type SensorSourceStatusResponse } from '@/api/modules/sensors';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { cn } from '@/lib/utils';
import MemoryPageFrame, {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_INFO_PANEL_CLASS,
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
  lastError: string | null;
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
    lastError: sensor?.last_error ?? null,
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

const loadSourceOverview = async () => Promise.all([
  memoryApi.getDashboard({ pending_limit: 8 }),
  sensorsApi.getStatus(),
]);

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

function SourceIcon({ row, className }: { row: SourceLedgerRow; className?: string }) {
  return (
    <span className={cn(
      'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.72)]',
      className
    )}>
      <PluginIcon
        iconId={row.icon}
        pluginId={row.pluginId}
        sourceName={row.key}
        className="h-4 w-4 text-[hsl(var(--memory-body))]"
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
}: {
  rows: SourceLedgerRow[];
  dashboard: MemoryDashboard | null;
}) {
  const { t } = useTranslation('app');
  const pulseRows = rows.slice(0, 6);
  const maxBatchCount = Math.max(1, ...pulseRows.map((row) => Math.max(row.lastResultCount ?? 0, 0)));
  const todayCount = dashboard?.deltas?.today?.l1_events ?? 0;
  const backlogCount = dashboard?.processing_backlog?.total_pending ?? 0;

  return (
    <section className={cn(MEMORY_SECTION_CARD_CLASS, 'overflow-hidden p-0')}>
      <div className="grid lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 px-5 py-5">
          <div className="min-w-0 space-y-1">
            <h1 className="text-[1.45rem] font-semibold text-[hsl(var(--memory-title))]">
              {t('memory.sourcesPage.sections.pulse')}
            </h1>
            <p className="max-w-2xl text-sm leading-6 text-[hsl(var(--memory-body))]">
              {t('memory.sourcesPage.pulseSubtitle')}
            </p>
          </div>

          {pulseRows.length > 0 ? (
            <div className="mt-5 divide-y divide-[hsl(var(--memory-divider)/0.5)]">
              {pulseRows.map((row) => {
                const value = Math.max(row.lastResultCount ?? 0, 0);
                const intensity = value > 0 ? Math.max(12, Math.round((value / maxBatchCount) * 100)) : 3;
                return (
                  <div
                    key={row.key}
                    className="grid gap-3 py-2.5 sm:grid-cols-[minmax(130px,190px)_minmax(0,1fr)_72px] sm:items-center"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--memory-panel-subtle)/0.72)]">
                        <PluginIcon
                          iconId={row.icon}
                          pluginId={row.pluginId}
                          sourceName={row.key}
                          className="h-3.5 w-3.5 text-[hsl(var(--memory-body))]"
                        />
                      </span>
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-[hsl(var(--memory-title))]">{row.label}</div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[hsl(var(--memory-muted))]">
                          <span className={`h-1.5 w-1.5 rounded-full ${sourceStatusDotClassName(row.status)}`} aria-hidden="true" />
                          <span className="truncate">{sourceStatusLabel(row.status, t)}</span>
                        </div>
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="h-2 overflow-hidden rounded-full bg-[hsl(var(--memory-panel-subtle)/0.58)]">
                        <div
                          className={cn(
                            'h-full rounded-full transition-[width] duration-300 ease-out',
                            value > 0
                              ? 'bg-[hsl(var(--memory-accent)/0.72)]'
                              : 'bg-[hsl(var(--memory-divider)/0.7)]'
                          )}
                          style={{ width: `${intensity}%` }}
                        />
                      </div>
                    </div>
                    <div className="flex items-baseline justify-between gap-2 sm:block sm:text-right">
                      <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{formatInteger(value)}</div>
                      <div className="text-[11px] text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.columns.today')}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className={cn(MEMORY_EMPTY_PANEL_CLASS, 'mt-5')}>{t('memory.sourcesPage.empty')}</div>
          )}
        </div>

        <div className="border-t border-[hsl(var(--memory-divider)/0.6)] bg-[hsl(var(--memory-panel-subtle)/0.24)] px-5 py-5 lg:border-l lg:border-t-0">
          <div className="grid grid-cols-3 gap-4 lg:grid-cols-1 lg:gap-5">
            <div>
              <div className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.pulseStats.today')}</div>
              <div className="mt-1 text-2xl font-semibold text-[hsl(var(--memory-title))]">{formatInteger(todayCount)}</div>
            </div>
            <div>
              <div className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.pulseStats.sources')}</div>
              <div className="mt-1 text-2xl font-semibold text-[hsl(var(--memory-title))]">{formatInteger(rows.length)}</div>
            </div>
            <div>
              <div className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.pulseStats.backlog')}</div>
              <div className="mt-1 text-2xl font-semibold text-[hsl(var(--memory-title))]">{formatInteger(backlogCount)}</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function SourceLedgerSection({ rows }: { rows: SourceLedgerRow[] }) {
  const { t, i18n } = useTranslation('app');

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
                      {formatInteger(row.lastResultCount ?? 0)}
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [dashboardPayload, sensorPayload] = await loadSourceOverview();
        if (cancelled) {
          return;
        }
        setDashboard(dashboardPayload);
        setSensorStatus(sensorPayload);
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
          <SourcePulseSection rows={rows} dashboard={dashboard} />
          <SourceLedgerSection rows={rows} />
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
  lastError: null,
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
          <SourceIcon row={row} className="h-12 w-12" />
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

function SourceDetailStats({ row }: { row: SourceLedgerRow }) {
  const { t, i18n } = useTranslation('app');
  const stats = [
    { label: t('memory.sourcesPage.columns.stored'), value: formatInteger(row.eventCount) },
    { label: t('memory.sourcesPage.columns.today'), value: formatInteger(row.lastResultCount ?? 0) },
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

function SourceRecentEvents({ events, loading }: { events: L1Event[]; loading: boolean }) {
  const { t, i18n } = useTranslation('app');
  return (
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.sourcesPage.detail.recentTitle')}
        </h2>
        <span className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.sourcesPage.detail.recentCount', { count: events.length })}</span>
      </div>
      <div className="mt-4 divide-y divide-[hsl(var(--memory-divider)/0.58)]">
        {loading ? (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>
            <div className="flex items-center gap-2">
              <LoadingSpinner className="h-4 w-4" />
              <span>{t('memory.sourcesPage.detail.eventsLoading')}</span>
            </div>
          </div>
        ) : events.length > 0 ? (
          events.map((event) => {
            const typeKey = `memory.eventTypes.${String(event.event_type || '').toLowerCase()}`;
            const typeLabel = t(typeKey);
            return (
              <article key={event.event_id} className="grid gap-2 py-3 md:grid-cols-[160px_minmax(0,1fr)_110px] md:items-start">
                <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                  {formatOverviewTimestamp(event.timestamp, i18n.language) || t('memory.sourcesPage.unknownTime')}
                </div>
                <div className="min-w-0">
                  <div className="line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-title))]">{event.content}</div>
                  <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                    {typeLabel === typeKey ? event.event_type : typeLabel}
                  </div>
                </div>
                <div className="text-xs text-[hsl(var(--memory-muted))] md:text-right">
                  {t('memory.sourcesPage.detail.stored')}
                </div>
              </article>
            );
          })
        ) : (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.sourcesPage.detail.eventsEmpty')}</div>
        )}
      </div>
    </section>
  );
}

function SourceUsageSection({ row }: { row: SourceLedgerRow }) {
  const { t } = useTranslation('app');
  const items = [
    t('memory.sourcesPage.detail.usage.recall'),
    t('memory.sourcesPage.detail.usage.summaries'),
    t('memory.sourcesPage.detail.usage.experiences'),
  ];
  return (
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
        {t('memory.sourcesPage.detail.usageTitle')}
      </h2>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {items.map((item, index) => (
          <div key={item} className={MEMORY_INFO_PANEL_CLASS}>
            <div className="mb-2 text-xs font-medium text-[hsl(var(--memory-muted))]">
              {t('memory.sourcesPage.detail.usageStep', { index: index + 1 })}
            </div>
            <div>{item}</div>
          </div>
        ))}
      </div>
      {row.lastError ? (
        <div className={cn(MEMORY_EMPTY_PANEL_CLASS, 'mt-4 text-red-600')}>
          {t('memory.sourcesPage.detail.lastError', { message: row.lastError })}
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
  const [events, setEvents] = useState<L1Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const loadPage = async (cancelledRef?: { cancelled: boolean }) => {
    setLoading(true);
    setEventsLoading(true);
    setError(null);
    try {
      const [dashboardPayload, sensorPayload, eventsPayload] = await Promise.all([
        memoryApi.getDashboard({ pending_limit: 8 }),
        sensorsApi.getStatus(),
        memoryApi.getL1Events({ source: sourceName, limit: 50, offset: 0 }),
      ]);
      if (cancelledRef?.cancelled) {
        return;
      }
      setDashboard(dashboardPayload);
      setSensorStatus(sensorPayload);
      setEvents(eventsPayload.items || []);
    } catch (err) {
      if (!cancelledRef?.cancelled) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (!cancelledRef?.cancelled) {
        setLoading(false);
        setEventsLoading(false);
      }
    }
  };

  useEffect(() => {
    const cancelledRef = { cancelled: false };
    void loadPage(cancelledRef);
    return () => {
      cancelledRef.cancelled = true;
    };
  }, [sourceName]);

  const rows = useMemo(
    () => buildSourceLedgerRows(dashboard?.source_counts || [], sensorStatus, t),
    [dashboard?.source_counts, sensorStatus, t],
  );
  const row = rows.find((item) => normalizeSourceKey(item.key) === normalizeSourceKey(sourceName))
    || fallbackSourceRow(sourceName, t);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await sensorsApi.requestSync(sourceName);
      await loadPage();
    } finally {
      setSyncing(false);
    }
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
          <SourceDetailStats row={row} />
          <SourceRecentEvents events={events} loading={eventsLoading} />
          <SourceUsageSection row={row} />
        </div>
      )}
    </MemoryPageFrame>
  );
};

export default MemorySourcesPage;
