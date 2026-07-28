import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { MEMORY_SECTION_SURFACE_CLASS } from '../MemoryPageFrame';
import {
  formatInteger,
  formatOverviewTimestamp,
  sourceStatusDotClassName,
  sourceStatusLabel,
  type SourceCoverageRow,
} from './overviewModel';

export function OverviewSourceCoverage({
  rows,
  processingBacklog,
}: {
  rows: SourceCoverageRow[];
  processingBacklog: number;
}) {
  const { t, i18n } = useTranslation('app');

  return (
    <section className={MEMORY_SECTION_SURFACE_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
          {t('memory.overview.sections.sources')}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <span>{t('memory.overview.sourceCount', { count: rows.length })}</span>
          {processingBacklog > 0 ? (
            <>
              <span className="h-1 w-1 rounded-full bg-[hsl(var(--memory-divider))]" aria-hidden="true" />
              <span>{t('memory.overview.processingBacklog', { count: processingBacklog })}</span>
            </>
          ) : null}
        </div>
      </div>
      {rows.length > 0 ? (
        <div className="mt-5 divide-y divide-[hsl(var(--memory-divider)/0.34)]">
          <div className="hidden grid-cols-[minmax(0,1fr)_120px_180px_140px] gap-2 pb-3 text-xs text-[hsl(var(--memory-muted))] md:grid">
            <div>{t('memory.overview.sourceColumns.source')}</div>
            <div>{t('memory.overview.sourceColumns.status')}</div>
            <div>{t('memory.overview.sourceColumns.sync')}</div>
            <div>{t('memory.overview.sourceColumns.events')}</div>
          </div>
          {rows.map((row) => {
            const syncLabel = formatOverviewTimestamp(row.lastSyncAt ?? row.lastEventAt, i18n.language)
              || t('memory.overview.sourceStatus.noEvents');
            const statusLabel = sourceStatusLabel(row.status, t);
            return (
              <div key={row.key} className="grid gap-3 py-4 md:grid-cols-[minmax(0,1fr)_120px_180px_140px] md:items-center">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.74)]">
                    <PluginIcon
                      iconId={row.icon}
                      className="h-4 w-4 text-[hsl(var(--memory-body))]"
                    />
                  </span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-[hsl(var(--memory-title))]">{row.label}</div>
                    <div className="text-xs text-[hsl(var(--memory-muted))] md:hidden">{statusLabel}</div>
                  </div>
                </div>
                <div className="hidden items-center gap-2 text-xs text-[hsl(var(--memory-body))] md:flex">
                  <span className={`h-2 w-2 rounded-full ${sourceStatusDotClassName(row.status)}`} aria-hidden="true" />
                  <span>{statusLabel}</span>
                </div>
                <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                  <div>{syncLabel}</div>
                  {row.lastResultCount != null ? (
                    <div>{t('memory.overview.sourceLastResult', { count: row.lastResultCount })}</div>
                  ) : null}
                </div>
                <div>
                  <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{formatInteger(row.eventCount)}</div>
                  <div className="text-xs text-[hsl(var(--memory-muted))] md:hidden">{t('memory.overview.sourceColumns.events')}</div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-5 flex flex-col gap-4 rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.46)] px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
              {t('memory.overview.empty.sources')}
            </div>
            <p className="mt-1 text-sm leading-6 text-[hsl(var(--memory-body))]">
              {t('memory.overview.empty.sourcesBody')}
            </p>
          </div>
          <Button asChild size="sm" variant="ghost" className="w-fit shrink-0 rounded-lg px-4">
            <Link to="/memory/sources">{t('memory.overview.actions.connectSource')}</Link>
          </Button>
        </div>
      )}
    </section>
  );
}
