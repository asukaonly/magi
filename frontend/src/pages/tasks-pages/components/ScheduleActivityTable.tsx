import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Square } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import type { ScheduleActivityDTO, ScheduleDTO } from '@/api';
import {
  getActivityTitle,
  getScheduleTargetLabelKey,
  getScheduleTargetLabelFallback,
} from '../utils/scheduleHelpers';
import { formatDuration, formatUnixSeconds } from '../utils/scheduleFormatters';
import { IconActionButton } from './IconActionButton';

export interface ScheduleActivityTableProps {
  activities: ScheduleActivityDTO[];
  schedulesById: Record<string, ScheduleDTO>;
  emptyMessage: string;
  stoppingActivityId: string | null;
  onStop: (a: ScheduleActivityDTO) => void;
  onOpenBackgroundTask: (taskId: string) => void;
}

export const ScheduleActivityTable: React.FC<ScheduleActivityTableProps> = ({
  activities,
  schedulesById,
  emptyMessage,
  stoppingActivityId,
  onStop,
  onOpenBackgroundTask,
}) => {
  const { t } = useTranslation('app');
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="w-[30%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
            <th className="w-[12%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.status')}</th>
            <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.plannedAt')}</th>
            <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.startedAt')}</th>
            <th className="w-[10%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.duration')}</th>
            <th className="w-[16%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {activities.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">{emptyMessage}</td>
            </tr>
          ) : activities.map((activity) => {
            const linked = schedulesById[activity.schedule_id];
            const typeLabel = linked
              ? t(getScheduleTargetLabelKey(linked), { defaultValue: getScheduleTargetLabelFallback(linked) })
              : t(`tasks.scheduled.targetTypes.${activity.target_type}`, { defaultValue: activity.target_type });
            return (
              <tr key={activity.activity_id} className="bg-background/60">
                <td className="px-4 py-3 align-middle">
                  <div className="truncate font-medium text-foreground" title={getActivityTitle(activity, schedulesById)}>
                    {getActivityTitle(activity, schedulesById)}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted-foreground">{typeLabel}</div>
                </td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground">
                  {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: activity.status })}
                </td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatUnixSeconds(activity.planned_at)}</td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatUnixSeconds(activity.started_at)}</td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatDuration(activity.duration_ms)}</td>
                <td className="px-4 py-3 align-middle">
                  <div className="flex justify-end gap-1">
                    {activity.background_task_id ? (
                      <IconActionButton
                        variant="outline"
                        label={t('tasks.scheduled.actions.viewBackgroundTask')}
                        icon={<ChevronRight className="h-3.5 w-3.5" />}
                        onClick={() => onOpenBackgroundTask(activity.background_task_id as string)}
                      />
                    ) : null}
                    {activity.cancellable ? (
                      <IconActionButton
                        variant="outline"
                        label={t('tasks.scheduled.actions.stop')}
                        disabled={stoppingActivityId === activity.activity_id}
                        icon={stoppingActivityId === activity.activity_id ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                        onClick={() => onStop(activity)}
                      />
                    ) : null}
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
