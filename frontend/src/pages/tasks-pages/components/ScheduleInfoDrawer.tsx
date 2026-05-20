import React from 'react';
import { useTranslation } from 'react-i18next';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import type { ScheduleDTO } from '@/api';
import { getScheduleTitle } from '../utils/scheduleHelpers';
import { formatUnixSeconds, getScheduleTriggerSummary } from '../utils/scheduleFormatters';

export interface ScheduleInfoDrawerProps {
  schedule: ScheduleDTO | null;
  onClose: () => void;
  onRun: (s: ScheduleDTO) => void;
  onToggle: (s: ScheduleDTO) => void;
}

export const ScheduleInfoDrawer: React.FC<ScheduleInfoDrawerProps> = ({
  schedule,
  onClose,
  onRun,
  onToggle,
}) => {
  const { t } = useTranslation('app');
  const open = Boolean(schedule);
  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="flex w-full max-w-none flex-col overflow-hidden sm:max-w-xl">
        {schedule ? (
          <>
            <SheetHeader className="shrink-0 border-b border-border/60 px-8 pb-5 pt-6 pr-12">
              <SheetTitle className="leading-snug">
                {t(`tasks.scheduled.systemJobs.${schedule.target_type}.title`, {
                  defaultValue: getScheduleTitle(schedule),
                })}
              </SheetTitle>
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6 text-sm">
              <p className="leading-6 text-muted-foreground">
                {t(`tasks.scheduled.systemJobs.${schedule.target_type}.description`, {
                  defaultValue: t('tasks.scheduled.systemJobs.fallbackDescription'),
                })}
              </p>
              <dl className="mt-5 grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.fields.triggerType')}</dt>
                  <dd className="mt-1 text-foreground">{getScheduleTriggerSummary(schedule)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.columns.lastRun')}</dt>
                  <dd className="mt-1 text-foreground">{formatUnixSeconds(schedule.target_state?.last_run_at)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.columns.nextRun')}</dt>
                  <dd className="mt-1 text-foreground">{formatUnixSeconds(schedule.target_state?.next_run_at)}</dd>
                </div>
                {schedule.target_state?.last_error ? (
                  <div className="sm:col-span-2">
                    <dt className="text-[11px] font-semibold uppercase tracking-wide text-red-500">{t('tasks.scheduled.fields.lastError')}</dt>
                    <dd className="mt-1 text-red-500">{schedule.target_state.last_error}</dd>
                  </div>
                ) : null}
              </dl>
            </div>
            <div className="shrink-0 px-8 pb-6 pt-3">
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => onRun(schedule)}>{t('tasks.scheduled.actions.runNow')}</Button>
                <Button variant="outline" size="sm" onClick={() => onToggle(schedule)}>
                  {schedule.enabled ? t('tasks.scheduled.actions.disable') : t('tasks.scheduled.actions.enable')}
                </Button>
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};
