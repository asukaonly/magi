import { CheckCircle2, Loader2, ScrollText, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { PluginInstallJobSnapshot } from '@/api/modules/plugins';
import { cn } from '@/lib/utils';

interface PluginInstallProgressPanelProps {
  snapshot: PluginInstallJobSnapshot | null;
  title: string;
  className?: string;
}

const statusIconClassName = 'h-4 w-4 shrink-0';

export const PluginInstallProgressPanel = ({
  snapshot,
  title,
  className,
}: PluginInstallProgressPanelProps): JSX.Element | null => {
  const { t } = useTranslation('app');

  if (!snapshot) {
    return null;
  }

  const progress = Math.max(0, Math.min(100, Math.round(snapshot.progress_pct ?? 0)));
  const isActive = snapshot.status === 'queued' || snapshot.status === 'running';
  const logs = snapshot.logs.slice(-80);
  const statusLabel = t(`settings.pluginInstallProgress.status.${snapshot.status}`);
  const stageLabel = t(`settings.pluginInstallProgress.stage.${snapshot.stage}`, {
    defaultValue: snapshot.stage,
  });

  return (
    <div className={cn('rounded-lg border border-border bg-muted/25 p-3', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            {snapshot.status === 'completed' ? (
              <CheckCircle2 className={cn(statusIconClassName, 'text-emerald-500')} />
            ) : snapshot.status === 'failed' ? (
              <XCircle className={cn(statusIconClassName, 'text-destructive')} />
            ) : (
              <Loader2 className={cn(statusIconClassName, 'animate-spin text-primary')} />
            )}
            <span className="truncate">{title}</span>
          </div>
          <div className="text-xs text-muted-foreground">
            {statusLabel} / {stageLabel} / {snapshot.message}
          </div>
        </div>
        <span className="shrink-0 text-xs font-medium text-muted-foreground">{progress}%</span>
      </div>

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-background"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div
          className={cn(
            'h-full rounded-full transition-all duration-300',
            snapshot.status === 'failed' ? 'bg-destructive' : 'bg-primary',
            isActive ? 'animate-pulse' : ''
          )}
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="mt-3 rounded-md border border-border/70 bg-background/80">
        <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-xs font-medium text-muted-foreground">
          <ScrollText className="h-3.5 w-3.5" />
          {t('settings.pluginInstallProgress.logsTitle')}
        </div>
        <div className="max-h-40 overflow-auto px-3 py-2 font-mono text-[11px] leading-5 text-muted-foreground">
          {logs.length > 0 ? (
            logs.map((entry, index) => (
              <div key={`${entry.ts_ms}-${entry.stage}-${index}`} className="whitespace-pre-wrap break-words">
                <span className={entry.level === 'error' ? 'text-destructive' : 'text-muted-foreground/80'}>
                  [{entry.stage}]
                </span>{' '}
                {entry.message}
              </div>
            ))
          ) : (
            <div>{t('settings.pluginInstallProgress.logsEmpty')}</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default PluginInstallProgressPanel;
