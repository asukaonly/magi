import { useTranslation } from 'react-i18next';
import type { MemoryDashboard } from '@/api/modules/memory';
import { formatBytes, formatInteger } from './overviewModel';

interface SummaryMetric {
  key: string;
  label: string;
  value: string;
  detail?: string;
  quiet?: boolean;
}

export function OverviewSummary({
  dashboard,
  sourceCount,
}: {
  dashboard: MemoryDashboard | null;
  sourceCount: number;
}) {
  const { t } = useTranslation('app');
  const todayDeltas = dashboard?.deltas?.today;
  const metrics: SummaryMetric[] = [
    {
      key: 'understanding',
      label: t('memory.overview.metrics.understanding'),
      value: formatInteger(dashboard?.statistics.l2.assertion_count ?? 0),
      detail: t('memory.overview.metricDelta.today', { value: formatInteger(todayDeltas?.l2_assertions ?? 0) }),
    },
    {
      key: 'summaries',
      label: t('memory.overview.metrics.summaries'),
      value: formatInteger(dashboard?.statistics.l3.summary_count ?? 0),
      detail: t('memory.overview.metricDelta.today', { value: formatInteger(todayDeltas?.l3_summaries ?? 0) }),
    },
    {
      key: 'sources',
      label: t('memory.overview.metrics.sources'),
      value: formatInteger(sourceCount),
    },
    {
      key: 'storage',
      label: t('memory.overview.metrics.storage'),
      value: formatBytes(dashboard?.statistics.disk_usage_bytes),
      quiet: true,
    },
  ];

  return (
    <section
      data-testid="memory-overview-summary"
      aria-label={t('memory.overview.summaryLabel')}
      className="px-1 pb-2 pt-3 sm:px-2 sm:pb-3 sm:pt-5"
    >
      <h1 className="sr-only">{t('memory.overview.title')}</h1>
      <div className="grid gap-8 xl:grid-cols-[minmax(13rem,0.75fr)_minmax(0,2.25fr)] xl:items-end xl:gap-14">
        <div>
          <div className="text-sm font-medium text-[hsl(var(--memory-body))]">
            {t('memory.overview.metrics.totalMemories')}
          </div>
          <div className="mt-2 text-[clamp(2.75rem,4.2vw,3.75rem)] font-semibold leading-none tracking-[-0.045em] text-[hsl(var(--memory-title))]">
            {formatInteger(dashboard?.statistics.total_memories ?? 0)}
          </div>
          <div className="mt-3 text-xs leading-5 text-[hsl(var(--memory-muted))]">
            {t('memory.overview.metricDelta.today', { value: formatInteger(todayDeltas?.total_memories ?? 0) })}
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-8 gap-y-7 sm:grid-cols-4">
          {metrics.map((metric) => (
            <div key={metric.key}>
              <dt className="text-xs leading-5 text-[hsl(var(--memory-muted))]">{metric.label}</dt>
              <dd
                className={
                  metric.quiet
                    ? 'mt-1.5 text-xl font-medium leading-none text-[hsl(var(--memory-body))]'
                    : 'mt-1.5 text-2xl font-semibold leading-none text-[hsl(var(--memory-title))]'
                }
              >
                {metric.value}
              </dd>
              {metric.detail ? (
                <div className="mt-2 text-xs leading-5 text-[hsl(var(--memory-muted))]">{metric.detail}</div>
              ) : null}
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
