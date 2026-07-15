import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import type { ScheduleDTO } from '@/api';
import { getScheduleTitle } from '../utils/scheduleHelpers';
import { formatUnixSeconds, getScheduleTriggerSummary } from '../utils/scheduleFormatters';

export interface ScheduleInfoDrawerProps {
  schedule: ScheduleDTO | null;
  onClose: () => void;
}

/**
 * Read-only preview drawer for a single schedule. Opened by clicking the
 * row body — the row no longer doubles as an "edit" trigger. For mutations
 * (edit / enable / run / delete), the user clicks the dedicated icon
 * buttons in the row.
 *
 * If we need to surface more diagnostic fields here later (recent
 * activity, target_payload contents, etc.) this is the place.
 */
export const ScheduleInfoDrawer: React.FC<ScheduleInfoDrawerProps> = ({
  schedule,
  onClose,
}) => {
  const { t, i18n } = useTranslation('app');
  const locale = i18n?.language;
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
              <SheetDescription className="sr-only">
                {t(`tasks.scheduled.systemJobs.${schedule.target_type}.description`, {
                  defaultValue: t('tasks.scheduled.systemJobs.fallbackDescription'),
                })}
              </SheetDescription>
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
                  <dd className="mt-1 text-foreground">{formatUnixSeconds(schedule.target_state?.last_run_at, locale)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.columns.nextRun')}</dt>
                  <dd className="mt-1 text-foreground">{formatUnixSeconds(schedule.target_state?.next_run_at, locale)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t('tasks.scheduled.fields.status', { defaultValue: '状态' })}
                  </dt>
                  <dd className="mt-1 text-foreground">
                    {schedule.enabled
                      ? t('tasks.scheduled.status.enabled', { defaultValue: '已启用' })
                      : t('tasks.scheduled.status.disabled', { defaultValue: '已禁用' })}
                  </dd>
                </div>
                {schedule.target_state?.last_error ? (
                  <div className="sm:col-span-2">
                    <dt className="text-[11px] font-semibold uppercase tracking-wide text-red-500">{t('tasks.scheduled.fields.lastError')}</dt>
                    <dd className="mt-1 text-red-500">{schedule.target_state.last_error}</dd>
                  </div>
                ) : null}
              </dl>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};
