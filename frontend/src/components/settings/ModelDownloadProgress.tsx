import { useTranslation } from 'react-i18next';
import type { components } from '@/api/generated/model-download-types';

export type DownloadProgress = components['schemas']['DownloadProgress'];

export function ModelDownloadProgress({ progress, active = false }: {
  progress: DownloadProgress | null;
  active?: boolean;
}) {
  const { t, i18n } = useTranslation('app');
  if (!active && (!progress || progress.phase === 'completed')) return null;
  const phase = progress?.phase ?? 'connecting';
  const total = progress?.total_bytes;
  const bytes = progress?.downloaded_bytes ?? 0;
  const ratio = total ? Math.min(1, bytes / total) : null;
  const formatSize = (value: number) => {
    const scale = value >= 1024 ** 3 ? 3 : value >= 1024 ** 2 ? 2 : value >= 1024 ? 1 : 0;
    const unit = ['B', 'KB', 'MB', 'GB'][scale];
    const size = value / 1024 ** scale;
    return `${new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(size)} ${unit}`;
  };
  const eta = progress?.eta_seconds;
  return <div className="mt-3 min-w-0 space-y-2" data-testid="model-download-progress">
    <div className="flex items-center justify-between gap-3 text-xs">
      <span role="status" className={phase === 'failed' ? 'text-destructive' : 'text-muted-foreground'}>{t(`modelDownload.phases.${phase}`)}</span>
      {ratio !== null && <span className="tabular-nums text-muted-foreground">{Math.floor(ratio * 100)}%</span>}
    </div>
    <div role="progressbar" aria-label={t('modelDownload.progress')} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={ratio === null ? undefined : Math.floor(ratio * 100)}
      className="h-1 overflow-hidden rounded-full bg-muted">
      <div className={`h-full origin-left rounded-full bg-primary ${ratio === null ? 'w-1/3 animate-pulse motion-reduce:animate-none' : 'transition-transform duration-300 ease-out motion-reduce:transition-none'}`}
        style={ratio === null ? undefined : { transform: `scaleX(${ratio})` }} />
    </div>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs tabular-nums text-muted-foreground">
      {(total !== null && total !== undefined || bytes > 0) && <span>{total ? `${formatSize(bytes)} / ${formatSize(total)}` : formatSize(bytes)}</span>}
      {progress && progress.speed_bps > 0 && <span>{formatSize(progress.speed_bps)}/s</span>}
      {eta !== null && eta !== undefined && <span>{t('modelDownload.remaining', { time: eta >= 60 ? t('modelDownload.minutes', { count: Math.ceil(eta / 60) }) : t('modelDownload.seconds', { count: Math.max(1, Math.ceil(eta / 5) * 5) }) })}</span>}
      {progress && progress.total_files > 8 && <span>{t('modelDownload.files', { done: progress.files_completed, total: progress.total_files })}</span>}
    </div>
  </div>;
}
