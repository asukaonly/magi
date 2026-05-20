import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import type { ScheduleDTO } from '@/api';
import { getScheduleTitle } from '../utils/scheduleHelpers';
import { formatUnixSeconds, getScheduleTriggerSummary } from '../utils/scheduleFormatters';

export interface ScheduleInfoDrawerProps {
  schedule: ScheduleDTO | null;
  onClose: () => void;
  onRun: (s: ScheduleDTO, overrideParams?: Record<string, unknown>) => void;
  onToggle: (s: ScheduleDTO) => void;
}

/**
 * Hints shown above the JSON textarea when "Run with custom params" is
 * expanded, per target_type. Keeps the generic mechanism but gives users
 * a clue about which params each handler honors. Add more here as new
 * handlers grow opt-in payload params.
 */
const PARAM_HINTS_BY_TARGET: Record<string, string> = {
  timeline_diary_narrative:
    '{"days": 7}  // 回填过去 7 天的日记（默认 1）',
};

export const ScheduleInfoDrawer: React.FC<ScheduleInfoDrawerProps> = ({
  schedule,
  onClose,
  onRun,
  onToggle,
}) => {
  const { t } = useTranslation('app');
  const [paramsOpen, setParamsOpen] = useState(false);
  const [paramsText, setParamsText] = useState('');
  const [paramsError, setParamsError] = useState<string | null>(null);

  // Reset override state whenever a different schedule opens
  useEffect(() => {
    setParamsOpen(false);
    setParamsText('');
    setParamsError(null);
  }, [schedule?.schedule_id]);

  const open = Boolean(schedule);
  const targetType = schedule?.target_type ?? '';
  const paramHint = PARAM_HINTS_BY_TARGET[targetType];

  const handleRunWithParams = () => {
    if (!schedule) return;
    const trimmed = paramsText.trim();
    if (!trimmed) {
      onRun(schedule);  // fallback to plain run
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(trimmed);
    } catch (err: any) {
      setParamsError(err?.message || 'invalid JSON');
      return;
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setParamsError('params must be a JSON object');
      return;
    }
    setParamsError(null);
    onRun(schedule, parsed);
  };

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

              {paramsOpen ? (
                <div className="mt-6 border-t border-border/60 pt-4">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t('tasks.scheduled.fields.overrideParams', { defaultValue: '本次运行参数 (JSON)' })}
                  </div>
                  {paramHint ? (
                    <div className="mb-2 font-mono text-[11px] leading-5 text-muted-foreground/80">
                      {paramHint}
                    </div>
                  ) : null}
                  <textarea
                    value={paramsText}
                    onChange={(e) => {
                      setParamsText(e.target.value);
                      if (paramsError) setParamsError(null);
                    }}
                    placeholder={paramHint ?? '{}'}
                    className="h-24 w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
                  />
                  {paramsError ? (
                    <div className="mt-1 text-xs text-red-500">{paramsError}</div>
                  ) : (
                    <div className="mt-1 text-[11px] text-muted-foreground/70">
                      {t('tasks.scheduled.fields.overrideParamsHint', {
                        defaultValue: '只影响这一次执行；下次定时触发时仍用原参数。',
                      })}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
            <div className="shrink-0 px-8 pb-6 pt-3">
              <div className="flex justify-end gap-2">
                {paramsOpen ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setParamsOpen(false);
                        setParamsText('');
                        setParamsError(null);
                      }}
                    >
                      {t('tasks.scheduled.actions.cancel', { defaultValue: '取消' })}
                    </Button>
                    <Button variant="default" size="sm" onClick={handleRunWithParams}>
                      {t('tasks.scheduled.actions.runWithParams', { defaultValue: '带参运行' })}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setParamsOpen(true)}
                    >
                      {t('tasks.scheduled.actions.runWithParamsOpen', { defaultValue: '带参运行…' })}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => onRun(schedule)}>
                      {t('tasks.scheduled.actions.runNow')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => onToggle(schedule)}>
                      {schedule.enabled ? t('tasks.scheduled.actions.disable') : t('tasks.scheduled.actions.enable')}
                    </Button>
                  </>
                )}
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};
