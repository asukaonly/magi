import { useTranslation } from 'react-i18next';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import {
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_SECTION_CARD_CLASS,
} from '../MemoryPageFrame';
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
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.overview.sections.sources')}
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <span>{t('memory.overview.sourceCount', { count: rows.length })}</span>
          <span className="text-[hsl(var(--memory-divider))]">/</span>
          <span>{t('memory.overview.processingBacklog', { count: processingBacklog })}</span>
        </div>
      </div>
      <div className="mt-3 divide-y divide-[hsl(var(--memory-divider)/0.6)]">
        {rows.length > 0 ? (
          <>
            <div className="hidden grid-cols-[minmax(0,1fr)_120px_180px_140px] gap-2 pb-2 text-xs text-[hsl(var(--memory-muted))] md:grid">
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
                <div key={row.key} className="grid gap-2 py-3 md:grid-cols-[minmax(0,1fr)_120px_180px_140px] md:items-center">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-subtle)/0.72)]">
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
          </>
        ) : (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.overview.empty.sources')}</div>
        )}
      </div>
    </section>
  );
}
