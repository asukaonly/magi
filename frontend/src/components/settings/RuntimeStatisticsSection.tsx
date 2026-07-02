import { useEffect, useMemo, useRef, useState, type FC } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Activity, RefreshCcw } from 'lucide-react';
import { metricsApi, type RuntimeOverview, type RuntimeOverviewSchedulerTarget } from '@/api/modules/metrics';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { StatisticsPageFrame } from './StatisticsPageFrame';

const AUTO_REFRESH_MS = 15000;
const MAX_SAMPLES = 12;

type RuntimeTrendPoint = {
  label: string;
  cpu: number;
  memory: number;
  ttft: number | null;
};

type LoadReason = 'initial' | 'manual' | 'poll';

const formatPercent = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}%` : null;

const formatLatency = (value?: number | null) =>
  typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}ms` : null;

const formatUpdatedAt = (timestamp?: number | null) => {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) {
    return '--';
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).format(new Date(timestamp));
};

const formatRuntimeClock = (timestamp?: number | null) => {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp <= 0) {
    return '--';
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).format(new Date(timestamp));
};

const getUnavailableFallback = (value: string | null, fallback: string) => value ?? fallback;

const buildTrendPoint = (overview: RuntimeOverview): RuntimeTrendPoint => ({
  label: formatRuntimeClock(overview.captured_at_ms),
  cpu: Number(overview.system.cpu_percent || 0),
  memory: Number(overview.system.memory_percent || 0),
  ttft:
    overview.model_execution.ttft_available && typeof overview.model_execution.avg_ttft_ms === 'number'
      ? overview.model_execution.avg_ttft_ms
      : null,
});

const getBottleneckKey = (overview: RuntimeOverview) => {
  if (overview.system.cpu_percent >= 85) return 'cpu';
  if (overview.system.memory_percent >= 85) return 'memory';
  if (overview.memory.total_pending > 0) return 'queue';
  if (
    overview.model_execution.core_model_success_rate_available &&
    (overview.model_execution.core_model_success_rate || 0) < 95
  ) {
    return 'success';
  }
  if (overview.model_execution.ttft_available && (overview.model_execution.avg_ttft_ms || 0) >= 1200) {
    return 'latency';
  }
  return 'stable';
};

const getHealthNoteKey = (overview: RuntimeOverview) => {
  if (overview.runtime.status !== 'ready') return 'runtimeOffline';
  if (overview.runtime.queue_backlog_healthy === false || overview.memory.total_pending >= 8) return 'queueBacklog';
  if (
    overview.model_execution.core_model_success_rate_available &&
    (overview.model_execution.core_model_success_rate || 0) < 95
  ) {
    return 'successDrift';
  }
  return 'queueHealthy';
};

const getStatusVariant = (status: string) => {
  if (status === 'ready') return 'success' as const;
  if (status === 'starting') return 'warning' as const;
  return 'outline' as const;
};

const resolveErrorMessage = (error: unknown) => {
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string') {
    return error.message;
  }
  return 'Unknown error';
};

export const RuntimeStatisticsSection: FC = () => <RuntimeStatisticsSectionInner />;

const RuntimeStatisticsSectionInner: FC = () => {
  const { t } = useTranslation('app');
  const [overview, setOverview] = useState<RuntimeOverview | null>(null);
  const [trendPoints, setTrendPoints] = useState<RuntimeTrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  const loadOverviewRef = useRef<((reason: LoadReason) => Promise<void>) | null>(null);

  useEffect(() => {
    mountedRef.current = true;

    const loadOverview = async (reason: LoadReason) => {
      if (!mountedRef.current) {
        return;
      }

      if (reason === 'initial') {
        setLoading(true);
      }
      if (reason === 'manual') {
        setRefreshing(true);
      }

      try {
        const response = await metricsApi.getRuntimeOverview();
        if (!mountedRef.current || !response.data) {
          return;
        }

        setOverview(response.data);
        setError(null);
        setTrendPoints((previous) => {
          const nextPoint = buildTrendPoint(response.data as RuntimeOverview);
          const next = [...previous, nextPoint];
          return next.slice(-MAX_SAMPLES);
        });
      } catch (loadError) {
        if (!mountedRef.current) {
          return;
        }
        setError(resolveErrorMessage(loadError));
      } finally {
        if (mountedRef.current) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };

    loadOverviewRef.current = loadOverview;
    void loadOverview('initial');

    const intervalId = window.setInterval(() => {
      void loadOverview('poll');
    }, AUTO_REFRESH_MS);

    return () => {
      mountedRef.current = false;
      loadOverviewRef.current = null;
      window.clearInterval(intervalId);
    };
  }, []);

  const signalValues = useMemo(() => {
    if (!overview) {
      return {
        cpu: null,
        memory: null,
        ttft: null,
        intentSuccess: null,
        coreSuccess: null,
      };
    }

    return {
      cpu: formatPercent(overview.system.cpu_percent),
      memory: formatPercent(overview.system.memory_percent),
      ttft:
        overview.model_execution.ttft_available
          ? formatLatency(overview.model_execution.avg_ttft_ms)
          : null,
      intentSuccess:
        overview.model_execution.intent_success_rate_available
          ? formatPercent(overview.model_execution.intent_success_rate)
          : null,
      coreSuccess:
        overview.model_execution.core_model_success_rate_available
          ? formatPercent(overview.model_execution.core_model_success_rate)
          : null,
    };
  }, [overview]);

  const statusLabel = overview ? t(`settings.statistics.runtime.status.${overview.runtime.status}`) : t('settings.statistics.shared.unavailable');
  const bottleneckLabel = overview
    ? t(`settings.statistics.runtime.bottlenecks.${getBottleneckKey(overview)}`)
    : t('settings.statistics.shared.unavailable');
  const healthNote = overview
    ? t(`settings.statistics.runtime.health.${getHealthNoteKey(overview)}`)
    : t('settings.statistics.shared.unavailable');

  const schedulerTargets = overview?.scheduler.recent_targets || [];

  if (loading && !overview) {
    return (
      <div data-testid="runtime-statistics-section" className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <LoadingSpinner />
          <span className="text-sm">{t('settings.usage.loading')}</span>
        </div>
      </div>
    );
  }

  if (!overview && error) {
    return (
      <div
        data-testid="runtime-statistics-section"
        className="space-y-4 rounded-[1.6rem] border border-dashed border-[hsl(var(--settings-subnav-border)/0.8)] bg-[hsl(var(--settings-shell-elevated)/0.28)] p-8"
      >
        <div className="space-y-2">
          <div className="text-lg font-semibold text-foreground">{t('settings.statistics.runtime.errorTitle')}</div>
          <div className="text-sm leading-6 text-muted-foreground">
            {t('settings.usage.loadFailed', { message: error })}
          </div>
        </div>
        <Button type="button" variant="outline" onClick={() => void loadOverviewRef.current?.('manual')}>
          {t('settings.statistics.runtime.refreshAction')}
        </Button>
      </div>
    );
  }

  return (
    <div data-testid="runtime-statistics-section" className="h-full min-h-0">
      <StatisticsPageFrame
        toolbar={(
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={overview ? getStatusVariant(overview.runtime.status) : 'outline'} className="gap-1 rounded-full px-3 py-1">
                <Activity className="h-3.5 w-3.5" />
                <span>{statusLabel}</span>
              </Badge>
              <div className="text-sm text-muted-foreground">{t('settings.statistics.runtime.autoRefresh')}</div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-sm text-muted-foreground">
                {t('settings.statistics.shared.updatedAt', {
                  time: formatUpdatedAt(overview?.captured_at_ms),
                })}
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void loadOverviewRef.current?.('manual')}
                disabled={refreshing}
                className="rounded-full bg-transparent"
              >
                <RefreshCcw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
                {t('settings.statistics.runtime.refreshAction')}
              </Button>
            </div>
          </>
        )}
        signalRibbon={(
          <>
            <SignalItem
              label={t('settings.statistics.runtime.cards.cpu')}
              value={getUnavailableFallback(signalValues.cpu, t('settings.statistics.shared.unavailable'))}
            />
            <SignalItem
              label={t('settings.statistics.runtime.cards.memory')}
              value={getUnavailableFallback(signalValues.memory, t('settings.statistics.shared.unavailable'))}
              detail={
                overview
                  ? `${overview.system.memory_used_gb.toFixed(1)} / ${overview.system.memory_total_gb.toFixed(1)} GB`
                  : undefined
              }
            />
            <SignalItem
              label={t('settings.statistics.runtime.cards.ttft')}
              value={getUnavailableFallback(signalValues.ttft, t('settings.statistics.shared.unavailable'))}
            />
            <SignalItem
              label={t('settings.statistics.runtime.cards.intentSuccess')}
              value={getUnavailableFallback(signalValues.intentSuccess, t('settings.statistics.shared.unavailable'))}
            />
            <SignalItem
              label={t('settings.statistics.runtime.cards.coreSuccess')}
              value={getUnavailableFallback(signalValues.coreSuccess, t('settings.statistics.shared.unavailable'))}
            />
            <SignalItem
              label={t('settings.statistics.runtime.cards.memoryQueue')}
              value={overview ? String(overview.memory.total_pending) : t('settings.statistics.shared.unavailable')}
              detail={
                overview
                  ? t('settings.statistics.runtime.summary.runtimeCommands', {
                      count: overview.runtime.pending_commands ?? 0,
                    })
                  : undefined
              }
            />
          </>
        )}
        mainCanvas={(
          <div className="space-y-5">
            <div className="flex items-center justify-between border-b border-[hsl(var(--settings-subnav-border)/0.45)] pb-3">
              <div className="text-sm font-medium text-foreground">{t('settings.statistics.runtime.trendTitle')}</div>
              <div className="text-xs text-muted-foreground">{t('settings.statistics.runtime.trendDesc')}</div>
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendPoints}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <YAxis yAxisId="utilization" tickLine={false} axisLine={false} width={48} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <YAxis yAxisId="ttft" orientation="right" tickLine={false} axisLine={false} width={52} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                  <Tooltip />
                  <Line yAxisId="utilization" type="monotone" dataKey="cpu" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                  <Line yAxisId="utilization" type="monotone" dataKey="memory" stroke="hsl(var(--accent))" strokeWidth={2} dot={false} />
                  <Line yAxisId="ttft" type="monotone" dataKey="ttft" stroke="hsl(var(--ring))" strokeWidth={2} dot={false} strokeDasharray="5 4" connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        secondary={(
          <div className="space-y-6">
            <div className="grid gap-6 md:grid-cols-3">
              <AnalysisSection
                title={t('settings.statistics.runtime.sections.schedulerTitle')}
                items={[
                  {
                    label: t('settings.statistics.runtime.scheduler.enabledSchedules'),
                    value: String(overview?.scheduler.enabled_schedule_count ?? 0),
                  },
                  {
                    label: t('settings.statistics.runtime.scheduler.runningTargets'),
                    value: String(overview?.scheduler.running_target_count ?? 0),
                  },
                  {
                    label: t('settings.statistics.runtime.scheduler.erroredTargets'),
                    value: String(overview?.scheduler.errored_target_count ?? 0),
                  },
                ]}
              />
              <AnalysisSection
                title={t('settings.statistics.runtime.sections.queueTitle')}
                items={[
                  {
                    label: t('settings.statistics.runtime.queue.l2Pending'),
                    value: String(overview?.memory.l2.total_pending ?? 0),
                  },
                  {
                    label: t('settings.statistics.runtime.queue.embeddingPending'),
                    value: String(overview?.memory.embeddings.total_pending ?? 0),
                  },
                  {
                    label: t('settings.statistics.runtime.queue.runtimePending'),
                    value: String(overview?.runtime.pending_commands ?? 0),
                  },
                ]}
              />
              <AnalysisSection
                title={t('settings.statistics.runtime.sections.healthTitle')}
                items={[
                  {
                    label: t('settings.statistics.runtime.health.queueStatus'),
                    value: overview?.runtime.queue_backlog_healthy
                      ? t('settings.statistics.runtime.health.good')
                      : t('settings.statistics.runtime.health.needsAttention'),
                  },
                  {
                    label: t('settings.statistics.runtime.health.workerStatus'),
                    value: overview?.runtime.runtime_status || t('settings.statistics.shared.unavailable'),
                  },
                ]}
              />
            </div>

            <section className="space-y-3 border-t border-[hsl(var(--settings-subnav-border)/0.42)]">
              <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
                {t('settings.statistics.runtime.sections.recentTasksTitle')}
              </div>
              <div className="space-y-3">
                {schedulerTargets.length > 0 ? (
                  schedulerTargets.slice(0, 3).map((target) => (
                    <SchedulerTargetRow key={`${target.target_type}-${target.target_key}`} target={target} />
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">
                    {t('settings.statistics.runtime.scheduler.noRecentTargets')}
                  </div>
                )}
              </div>
            </section>
          </div>
        )}
        summaryRail={(
          <>
            <SummaryItem
              label={t('settings.statistics.runtime.summary.status')}
              value={statusLabel}
              detail={overview?.runtime.runtime_status || undefined}
            />
            <SummaryItem
              label={t('settings.statistics.runtime.summary.attention')}
              value={bottleneckLabel}
              detail={healthNote}
            />
            <SummaryItem
              label={t('settings.statistics.runtime.summary.queueHealth')}
              value={`${overview?.memory.total_pending ?? 0}`}
              detail={t('settings.statistics.runtime.summary.queueDetail', {
                runtime: overview?.runtime.pending_commands ?? 0,
                scheduler: overview?.scheduler.upcoming_target_count ?? 0,
              })}
            />
            <div className="rounded-[1.25rem] border border-[hsl(var(--settings-subnav-border)/0.48)] bg-[hsl(var(--settings-shell-elevated)/0.24)] p-4 text-sm leading-6 text-muted-foreground">
              {healthNote}
            </div>
          </>
        )}
      />
    </div>
  );
};

const SignalItem = ({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) => (
  <div className="border-b border-[hsl(var(--settings-subnav-border)/0.42)] pb-3 md:border-b-0 md:pb-0">
    <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
    <div className="mt-2 text-2xl font-semibold text-foreground">{value}</div>
    {detail ? <div className="mt-1 text-xs text-muted-foreground">{detail}</div> : null}
  </div>
);

const AnalysisSection = ({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; value: string; meta?: string }>;
}) => (
  <section className="space-y-3 border-t border-[hsl(var(--settings-subnav-border)/0.42)]">
    <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{title}</div>
    <div className="space-y-3">
      {items.map((item) => (
        <div key={`${title}-${item.label}`} className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground">{item.label}</div>
            {item.meta ? <div className="text-xs text-muted-foreground">{item.meta}</div> : null}
          </div>
          <div className="text-sm text-foreground">{item.value}</div>
        </div>
      ))}
    </div>
  </section>
);

const SummaryItem = ({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) => (
  <div className="border-b border-[hsl(var(--settings-subnav-border)/0.38)] pb-4">
    <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
    <div className="mt-2 text-lg font-semibold text-foreground">{value}</div>
    {detail ? <div className="mt-1 text-sm text-muted-foreground">{detail}</div> : null}
  </div>
);

const SchedulerTargetRow = ({ target }: { target: RuntimeOverviewSchedulerTarget }) => {
  const { t } = useTranslation('app');
  return (
  <div className="flex items-start justify-between gap-4 border-b border-[hsl(var(--settings-subnav-border)/0.24)] pb-3">
    <div className="min-w-0">
      <div className="truncate text-sm font-medium text-foreground">{target.target_key}</div>
      <div className="text-xs text-muted-foreground">{target.target_type}</div>
    </div>
    <div className="text-right text-xs text-muted-foreground">
      <div>{target.running ? t('settings.statistics.runtime.scheduler.running') : t('settings.statistics.runtime.scheduler.idle')}</div>
      {typeof target.next_run_at === 'number' ? <div>{formatRuntimeClock(target.next_run_at * 1000)}</div> : null}
    </div>
  </div>
  );
};

export default RuntimeStatisticsSection;
