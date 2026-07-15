import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Square } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import type { ScheduleActivityDTO, ScheduleDTO } from '@/api';
import {
  getActivityTitle,
  getScheduleTargetLabelKey,
  getScheduleTargetLabelFallback,
} from '../utils/scheduleHelpers';
import { formatDuration, formatScheduleTableTime } from '../utils/scheduleFormatters';
import { IconActionButton } from './IconActionButton';

export interface ScheduleActivityTableProps {
  activities: ScheduleActivityDTO[];
  schedulesById: Record<string, ScheduleDTO>;
  emptyMessage: string;
  stoppingActivityId: string | null;
  onStop: (a: ScheduleActivityDTO) => void;
  onOpenBackgroundTask: (taskId: string) => void;
  onSelectActivity?: (a: ScheduleActivityDTO) => void;
}

// An activity row is "inspectable" when there's something meaningful in the
// detail drawer — i.e. it's a finished/cancelled execution (status carries
// timing + result_message + error + stats). Upcoming/queued rows have nothing
// to show beyond what's already in the table, so we don't make them clickable.
const isInspectable = (activity: ScheduleActivityDTO): boolean => {
  return (
    activity.activity_id.startsWith('execution:') ||
    activity.status === 'succeeded' ||
    activity.status === 'failed' ||
    activity.status === 'cancelled' ||
    activity.status === 'running'
  );
};

const statusDotClass = (status: string): string => {
  switch (status) {
    case 'running': return 'bg-primary';
    case 'queued': return 'bg-amber-500';
    case 'succeeded': return 'bg-emerald-500/70';
    case 'failed': return 'bg-destructive';
    case 'cancelled': return 'bg-muted-foreground/45';
    default: return 'bg-muted-foreground/45';
  }
};

const statusTextClass = (status: string): string => {
  if (status === 'failed') return 'text-destructive';
  if (status === 'running') return 'font-medium text-foreground';
  return 'text-muted-foreground';
};

export const ScheduleActivityTable: React.FC<ScheduleActivityTableProps> = ({
  activities,
  schedulesById,
  emptyMessage,
  stoppingActivityId,
  onStop,
  onOpenBackgroundTask,
  onSelectActivity,
}) => {
  const { t, i18n } = useTranslation('app');
  const locale = i18n?.language;
  const todayLabel = t('tasks.scheduled.filters.window.today');
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="border-b border-border/45 text-xs text-muted-foreground">
          <tr>
            <th className="w-[36%] px-4 py-3 font-semibold">{t('tasks.scheduled.columns.name')}</th>
            <th className="w-[14%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.status')}</th>
            <th className="w-[30%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.executedAt')}</th>
            <th className="w-[20%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.duration')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/35">
          {activities.length === 0 ? (
            <tr>
              <td colSpan={4} className="px-4 py-12 text-center text-xs text-muted-foreground">{emptyMessage}</td>
            </tr>
          ) : activities.map((activity) => {
            const linked = schedulesById[activity.schedule_id];
            const typeLabel = linked
              ? t(getScheduleTargetLabelKey(linked), { defaultValue: getScheduleTargetLabelFallback(linked) })
              : t(`tasks.scheduled.targetTypes.${activity.target_type}`, { defaultValue: activity.target_type });
            const clickable = Boolean(onSelectActivity) && isInspectable(activity);
            const hasInlineActions = Boolean(activity.background_task_id || activity.cancellable);
            const executionTime = activity.started_at ?? activity.planned_at;
            const delayed = Boolean(
              activity.started_at
              && activity.planned_at
              && Math.abs(activity.started_at - activity.planned_at) >= 60,
            );
            return (
              <tr
                key={activity.activity_id}
                className={cn(
                  'group transition-colors duration-200',
                  clickable && 'cursor-pointer hover:bg-muted/25',
                )}
                onClick={() => { if (clickable) onSelectActivity?.(activity); }}
              >
                <td className="px-4 py-3.5 align-middle">
                  <div className="truncate text-sm font-semibold text-foreground" title={getActivityTitle(activity, schedulesById)}>
                    {getActivityTitle(activity, schedulesById)}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted-foreground">{typeLabel}</div>
                </td>
                <td className="px-4 py-3.5 align-middle text-xs">
                  <span className={cn('inline-flex items-center gap-2', statusTextClass(activity.status))}>
                    <span className={cn('h-1.5 w-1.5 rounded-full', statusDotClass(activity.status))} />
                    {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: activity.status })}
                  </span>
                </td>
                <td className="px-4 py-3.5 align-middle text-xs tabular-nums text-muted-foreground">
                  <div>{formatScheduleTableTime(executionTime, locale, todayLabel)}</div>
                  {delayed ? (
                    <div className="mt-1 text-[11px] text-muted-foreground/70">
                      {t('tasks.scheduled.activity.plannedFor', {
                        time: formatScheduleTableTime(activity.planned_at, locale, todayLabel),
                      })}
                    </div>
                  ) : null}
                </td>
                <td className="px-4 py-3.5 align-middle text-xs text-muted-foreground">
                  <div className="flex items-center justify-between gap-2">
                    <span className="whitespace-nowrap tabular-nums">{formatDuration(activity.duration_ms, t)}</span>
                    <div className="flex items-center gap-0.5">
                      {activity.background_task_id ? (
                        <IconActionButton
                          variant="ghost"
                          label={t('tasks.scheduled.actions.viewBackgroundTask')}
                          icon={<ChevronRight className="h-3.5 w-3.5" />}
                          className="text-muted-foreground hover:text-foreground"
                          onClick={(e) => { e.stopPropagation(); onOpenBackgroundTask(activity.background_task_id as string); }}
                        />
                      ) : null}
                      {activity.cancellable ? (
                        <IconActionButton
                          variant="ghost"
                          label={t('tasks.scheduled.actions.stop')}
                          disabled={stoppingActivityId === activity.activity_id}
                          icon={stoppingActivityId === activity.activity_id ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                          className="text-muted-foreground hover:text-foreground"
                          onClick={(e) => { e.stopPropagation(); onStop(activity); }}
                        />
                      ) : null}
                      {clickable && !hasInlineActions ? (
                        <ChevronRight
                          aria-hidden
                          className="h-4 w-4 text-muted-foreground/35 opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                        />
                      ) : null}
                    </div>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
