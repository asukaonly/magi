import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import type { ScheduleActivityDTO, ScheduleDTO } from '@/api';
import { getActivityTitle, getScheduleTargetLabelFallback, getScheduleTargetLabelKey } from '../utils/scheduleHelpers';
import { formatDuration, formatUnixSeconds } from '../utils/scheduleFormatters';

export interface ActivityDetailDrawerProps {
  activity: ScheduleActivityDTO | null;
  schedulesById: Record<string, ScheduleDTO>;
  onClose: () => void;
}

const labelClass = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground';
const sectionClass = 'rounded-lg bg-muted/20 p-5';

const renderJsonPreview = (data: unknown): string => {
  if (!data || (typeof data === 'object' && Object.keys(data as object).length === 0)) {
    return '';
  }
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
};

const statusToneClass = (status: string): string => {
  switch (status) {
    case 'running': return 'bg-emerald-500/15 text-emerald-500';
    case 'queued':
    case 'upcoming': return 'bg-amber-500/15 text-amber-500';
    case 'succeeded': return 'bg-primary/15 text-primary';
    case 'failed': return 'bg-red-500/15 text-red-500';
    case 'cancelled': return 'bg-muted text-muted-foreground';
    default: return 'bg-muted text-muted-foreground';
  }
};

export const ActivityDetailDrawer: React.FC<ActivityDetailDrawerProps> = ({
  activity,
  schedulesById,
  onClose,
}) => {
  const { t, i18n } = useTranslation('app');
  const locale = i18n?.language;
  const open = Boolean(activity);
  const linkedSchedule = activity ? schedulesById[activity.schedule_id] : undefined;
  const typeLabel = linkedSchedule
    ? t(getScheduleTargetLabelKey(linkedSchedule), { defaultValue: getScheduleTargetLabelFallback(linkedSchedule) })
    : activity
      ? t(`tasks.scheduled.targetTypes.${activity.target_type}`, { defaultValue: activity.target_type })
      : '';
  const statsPreview = activity ? renderJsonPreview(activity.stats) : '';

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="flex w-full max-w-none flex-col overflow-hidden sm:max-w-xl lg:max-w-2xl">
        {activity ? (
          <>
            <SheetHeader className="shrink-0 border-b border-border/60 px-8 pb-5 pt-6 pr-12">
              <SheetTitle className="leading-snug">
                {getActivityTitle(activity, schedulesById)}
              </SheetTitle>
              <SheetDescription className="sr-only">
                {typeLabel} · {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: String(activity.status) })}
              </SheetDescription>
            </SheetHeader>

            <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
              <div className="space-y-5 pb-2 text-sm">
                <section className={sectionClass}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide',
                        statusToneClass(String(activity.status)),
                      )}
                    >
                      {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: String(activity.status) })}
                    </span>
                    {activity.manual ? (
                      <span className="rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-[10px] uppercase tracking-wide">
                        {t('tasks.scheduled.activity.manual', { defaultValue: 'Manual' })}
                      </span>
                    ) : null}
                  </div>
                  <dl className="mt-4 grid gap-4 sm:grid-cols-2">
                    <div>
                      <dt className={labelClass}>{t('tasks.scheduled.columns.type')}</dt>
                      <dd className="mt-1 text-foreground">{typeLabel}</dd>
                    </div>
                    <div>
                      <dt className={labelClass}>{t('tasks.scheduled.columns.duration')}</dt>
                      <dd className="mt-1 text-foreground">{formatDuration(activity.duration_ms, t)}</dd>
                    </div>
                    <div>
                      <dt className={labelClass}>{t('tasks.scheduled.columns.startedAt')}</dt>
                      <dd className="mt-1 text-foreground">{formatUnixSeconds(activity.started_at, locale)}</dd>
                    </div>
                    <div>
                      <dt className={labelClass}>{t('tasks.scheduled.activity.finishedAt', { defaultValue: 'Finished' })}</dt>
                      <dd className="mt-1 text-foreground">{formatUnixSeconds(activity.finished_at, locale)}</dd>
                    </div>
                    <div className="sm:col-span-2 min-w-0">
                      <dt className={labelClass}>Schedule ID</dt>
                      <dd className="mt-1 truncate font-mono text-xs text-foreground">{activity.schedule_id}</dd>
                    </div>
                    {activity.activity_id.startsWith('execution:') ? (
                      <div className="sm:col-span-2 min-w-0">
                        <dt className={labelClass}>Execution ID</dt>
                        <dd className="mt-1 truncate font-mono text-xs text-foreground">
                          {activity.activity_id.slice('execution:'.length)}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </section>

                {activity.result_message ? (
                  <section className={sectionClass}>
                    <h3 className={labelClass}>
                      {t('tasks.scheduled.activity.resultMessage', { defaultValue: 'Result message' })}
                    </h3>
                    <p className="mt-2 whitespace-pre-wrap leading-6 text-foreground">{activity.result_message}</p>
                  </section>
                ) : null}

                {activity.error ? (
                  <section className="rounded-lg bg-red-500/5 p-5">
                    <h3 className={cn(labelClass, 'text-red-500')}>
                      {t('tasks.fields.error')}
                    </h3>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-red-500">{activity.error}</p>
                  </section>
                ) : null}

                {statsPreview ? (
                  <section className={sectionClass}>
                    <h3 className={labelClass}>
                      {t('tasks.scheduled.activity.stats', { defaultValue: 'Stats' })}
                    </h3>
                    <pre className="mt-3 max-h-64 overflow-auto rounded-md bg-background/70 p-3 font-mono text-xs leading-5 text-muted-foreground">
                      {statsPreview}
                    </pre>
                  </section>
                ) : null}
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};
