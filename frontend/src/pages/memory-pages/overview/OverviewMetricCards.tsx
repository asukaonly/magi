import { type ComponentType } from 'react';
import { Box, FileText, HardDrive, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { MemoryDashboard } from '@/api/modules/memory';
import { MEMORY_SECTION_CARD_CLASS } from '../MemoryPageFrame';
import { formatBytes, formatInteger } from './overviewModel';

interface OverviewMetric {
  key: string;
  label: string;
  value: string;
  secondary: string;
  icon: ComponentType<{ className?: string }>;
}

export function OverviewMetricCards({ dashboard }: { dashboard: MemoryDashboard | null }) {
  const { t } = useTranslation('app');
  const todayDeltas = dashboard?.deltas?.today;
  const metrics: OverviewMetric[] = [
    {
      key: 'total',
      label: t('memory.overview.metrics.totalMemories'),
      value: formatInteger(dashboard?.statistics.total_memories ?? 0),
      secondary: t('memory.overview.metricDelta.today', { value: formatInteger(todayDeltas?.total_memories ?? 0) }),
      icon: Box,
    },
    {
      key: 'understanding',
      label: t('memory.overview.metrics.understanding'),
      value: formatInteger(dashboard?.statistics.l2.assertion_count ?? 0),
      secondary: t('memory.overview.metricDelta.today', { value: formatInteger(todayDeltas?.l2_assertions ?? 0) }),
      icon: UserRound,
    },
    {
      key: 'summaries',
      label: t('memory.overview.metrics.summaries'),
      value: formatInteger(dashboard?.statistics.l3.summary_count ?? 0),
      secondary: t('memory.overview.metricDelta.today', { value: formatInteger(todayDeltas?.l3_summaries ?? 0) }),
      icon: FileText,
    },
    {
      key: 'storage',
      label: t('memory.overview.metrics.storage'),
      value: formatBytes(dashboard?.statistics.disk_usage_bytes),
      secondary: t('memory.overview.metricDelta.current'),
      icon: HardDrive,
    },
  ];

  return (
    <section className="grid gap-3 md:grid-cols-4">
      {metrics.map((metric) => (
        <div key={metric.key} className={MEMORY_SECTION_CARD_CLASS}>
          <div className="flex min-h-[92px] items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.72)] text-[hsl(var(--memory-accent))]">
              <metric.icon className="h-4 w-4" />
            </div>
            <div className="min-w-0 pt-0.5">
              <div className="truncate text-sm font-medium text-[hsl(var(--memory-body))]">{metric.label}</div>
              <div className="mt-2 text-3xl font-semibold leading-none text-[hsl(var(--memory-title))]">{metric.value}</div>
              <div className="mt-3 text-xs leading-4 text-[hsl(var(--memory-muted))]">{metric.secondary}</div>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}
