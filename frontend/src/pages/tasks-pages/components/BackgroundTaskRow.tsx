import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';

import type { BackgroundTaskDTO, BackgroundTaskStatus } from '@/api';
import { cn } from '@/lib/utils';
import { formatUnixSeconds } from '../utils/scheduleFormatters';

export const statusToneClass = (status: BackgroundTaskStatus): string => {
  switch (status) {
    case 'running':
      return 'bg-emerald-500/15 text-emerald-500';
    case 'pending':
      return 'bg-amber-500/15 text-amber-500';
    case 'cancelling':
      return 'bg-orange-500/15 text-orange-500';
    case 'cancelled':
      return 'bg-muted text-muted-foreground';
    case 'succeeded':
      return 'bg-primary/15 text-primary';
    case 'failed':
      return 'bg-red-500/15 text-red-500';
    default:
      return 'bg-muted text-muted-foreground';
  }
};

export interface BackgroundTaskRowProps {
  task: BackgroundTaskDTO;
  onSelect: (taskId: string) => void;
}

export const BackgroundTaskRow: React.FC<BackgroundTaskRowProps> = ({ task, onSelect }) => {
  const { t } = useTranslation('app');
  return (
    <button
      type="button"
      onClick={() => onSelect(task.task_id)}
      className="group flex w-full items-center justify-between gap-4 rounded-lg border border-border/60 bg-background/70 px-4 py-3 text-left transition hover:border-border/80 hover:bg-muted/35"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">
            {task.spec.title || task.spec.goal || task.task_id}
          </span>
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide',
              statusToneClass(task.status),
            )}
          >
            {t(`tasks.status.${task.status}`)}
          </span>
        </div>
        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
          {task.spec.goal}
        </p>
        <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground">
          <span>{t('tasks.fields.created')}: {formatUnixSeconds(task.created_at)}</span>
          {task.started_at ? (
            <span>{t('tasks.fields.started')}: {formatUnixSeconds(task.started_at)}</span>
          ) : null}
          {task.finished_at ? (
            <span>{t('tasks.fields.finished')}: {formatUnixSeconds(task.finished_at)}</span>
          ) : null}
        </div>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:text-foreground" />
    </button>
  );
};
