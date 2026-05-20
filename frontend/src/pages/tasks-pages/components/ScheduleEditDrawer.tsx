import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import {
  schedulesApi,
  type ScheduleDTO,
  type ScheduleTriggerType,
  type UpdateScheduleRequest,
} from '@/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';

import {
  getSchedulePrompt,
  getScheduleTargetKindFallback,
  getScheduleTargetKindLabelKey,
  getScheduleTitle,
  isPromptBackedSchedule,
} from '../utils/scheduleHelpers';
import { toFiniteNumber } from '../utils/scheduleFormatters';

export interface ScheduleEditDrawerProps {
  schedule: ScheduleDTO | null;
  onClose: () => void;
  onSaved: () => void;
}

const secondsToLocalInput = (seconds: number | null): string => {
  if (!seconds) return '';
  const date = new Date(seconds * 1000);
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
};

const drawerFieldLabelClass = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground';
const drawerSectionClass = 'rounded-lg border border-border/60 bg-background/70 p-5';

export const ScheduleEditDrawer: React.FC<ScheduleEditDrawerProps> = ({ schedule, onClose, onSaved }) => {
  const { t } = useTranslation('app');
  const [enabled, setEnabled] = useState(true);
  const [triggerType, setTriggerType] = useState<ScheduleTriggerType>('interval');
  const [intervalSeconds, setIntervalSeconds] = useState('300');
  const [onceRunAt, setOnceRunAt] = useState('');
  const [cronConfig, setCronConfig] = useState('{}');
  const [targetPrompt, setTargetPrompt] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!schedule) return;
    setEnabled(schedule.enabled);
    setTriggerType(schedule.trigger.trigger_type);
    setIntervalSeconds(String(toFiniteNumber(schedule.trigger.config.seconds) ?? 300));
    setOnceRunAt(secondsToLocalInput(toFiniteNumber(schedule.trigger.config.run_at)));
    setCronConfig(JSON.stringify(schedule.trigger.config || {}, null, 2));
    setTargetPrompt(getSchedulePrompt(schedule));
  }, [schedule]);

  const handleSave = async () => {
    if (!schedule) return;
    let config: Record<string, unknown>;
    if (triggerType === 'interval') {
      const seconds = Number(intervalSeconds);
      if (!Number.isFinite(seconds) || seconds < 1) {
        toast.error(t('tasks.scheduled.feedback.invalidInterval'));
        return;
      }
      config = { seconds };
    } else if (triggerType === 'once') {
      const timestamp = Date.parse(onceRunAt) / 1000;
      if (!Number.isFinite(timestamp)) {
        toast.error(t('tasks.scheduled.feedback.invalidRunAt'));
        return;
      }
      config = { run_at: timestamp };
    } else {
      try {
        config = JSON.parse(cronConfig || '{}') as Record<string, unknown>;
      } catch {
        toast.error(t('tasks.scheduled.feedback.invalidCron'));
        return;
      }
    }
    const updateBody: UpdateScheduleRequest = {
      enabled,
      trigger: {
        trigger_type: triggerType,
        config,
      },
    };
    if (isPromptBackedSchedule(schedule)) {
      const prompt = targetPrompt.trim();
      if (!prompt) {
        toast.error(t('tasks.scheduled.feedback.invalidPrompt'));
        return;
      }
      updateBody.target_payload = {
        ...(schedule.target_payload || {}),
        prompt,
      };
    }
    setSaving(true);
    try {
      await schedulesApi.update(schedule.schedule_id, updateBody);
      toast.success(t('tasks.scheduled.feedback.saveSuccess'));
      onSaved();
      onClose();
    } catch {
      toast.error(t('tasks.scheduled.feedback.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet open={Boolean(schedule)} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="flex w-full max-w-none flex-col overflow-hidden sm:max-w-2xl lg:max-w-3xl">
        <SheetHeader className="shrink-0 border-b border-border/60 px-8 pb-5 pt-6 pr-12">
          <SheetTitle className="leading-snug">{schedule ? getScheduleTitle(schedule) : t('tasks.scheduled.edit.title')}</SheetTitle>
        </SheetHeader>
        {schedule ? (
          <div className="flex min-h-0 flex-1 flex-col text-sm">
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-8 py-6">
              <div className="grid gap-3 rounded-lg border border-border/60 bg-background/80 p-5 shadow-sm sm:grid-cols-2">
                <div className="min-w-0">
                  <div className={drawerFieldLabelClass}>Schedule ID</div>
                  <div className="mt-1 truncate font-mono text-xs text-foreground">{schedule.schedule_id}</div>
                </div>
                <div>
                  <div className={drawerFieldLabelClass}>{t('tasks.scheduled.columns.type')}</div>
                  <div className="mt-1 text-sm text-foreground">
                    {t(`tasks.scheduled.targetTypes.${schedule.target_type}`, { defaultValue: schedule.target_type })}
                  </div>
                </div>
              </div>

              <section className={drawerSectionClass}>
                <div className="grid gap-4">
                  <div>
                    <div className={drawerFieldLabelClass}>{t('tasks.scheduled.fields.targetType')}</div>
                    <div className="mt-2 inline-flex rounded-md border border-border/60 bg-muted/45 px-2.5 py-1 text-xs font-medium text-foreground">
                      {t(`tasks.scheduled.targetKinds.${getScheduleTargetKindLabelKey(schedule)}`, {
                        defaultValue: getScheduleTargetKindFallback(schedule),
                      })}
                    </div>
                  </div>
                  {isPromptBackedSchedule(schedule) ? (
                    <label className="block space-y-2">
                      <span className={drawerFieldLabelClass}>{t('tasks.scheduled.fields.promptText')}</span>
                      <Textarea
                        value={targetPrompt}
                        onChange={(event) => setTargetPrompt(event.target.value)}
                        rows={6}
                        className="min-h-[150px] resize-y leading-6"
                      />
                    </label>
                  ) : (
                    <div className="space-y-2">
                      <div className={drawerFieldLabelClass}>{t('tasks.scheduled.fields.targetPayload')}</div>
                      <pre className="max-h-56 overflow-auto rounded-md border border-border/60 bg-muted/40 p-3 font-mono text-xs leading-5 text-muted-foreground">
                        {JSON.stringify(schedule.target_payload || {}, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </section>

              <section className={drawerSectionClass}>
                <label className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="font-medium text-foreground">{t('tasks.scheduled.fields.enabled')}</div>
                    <p className="text-xs text-muted-foreground">
                      {t('tasks.scheduled.fields.triggerType')}: {t(`tasks.scheduled.triggerTypes.${triggerType}`)}
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(event) => setEnabled(event.target.checked)}
                    className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                  />
                </label>
              </section>

              <section className={drawerSectionClass}>
                <div className="grid gap-4">
                  <label className="block space-y-2">
                    <span className={drawerFieldLabelClass}>
                      {t('tasks.scheduled.fields.triggerType')}
                    </span>
                    <select
                      value={triggerType}
                      onChange={(event) => setTriggerType(event.target.value as ScheduleTriggerType)}
                      className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    >
                      <option value="interval">{t('tasks.scheduled.triggerTypes.interval')}</option>
                      <option value="once">{t('tasks.scheduled.triggerTypes.once')}</option>
                      <option value="cron">{t('tasks.scheduled.triggerTypes.cron')}</option>
                    </select>
                  </label>

                  {triggerType === 'interval' ? (
                    <label className="block space-y-2">
                      <span className={drawerFieldLabelClass}>
                        {t('tasks.scheduled.fields.intervalSeconds')}
                      </span>
                      <Input
                        type="number"
                        min={1}
                        value={intervalSeconds}
                        onChange={(event) => setIntervalSeconds(event.target.value)}
                      />
                    </label>
                  ) : null}

                  {triggerType === 'once' ? (
                    <label className="block space-y-2">
                      <span className={drawerFieldLabelClass}>
                        {t('tasks.scheduled.fields.runAt')}
                      </span>
                      <Input
                        type="datetime-local"
                        value={onceRunAt}
                        onChange={(event) => setOnceRunAt(event.target.value)}
                      />
                    </label>
                  ) : null}

                  {triggerType === 'cron' ? (
                    <label className="block space-y-2">
                      <span className={drawerFieldLabelClass}>
                        {t('tasks.scheduled.fields.cronConfig')}
                      </span>
                      <Textarea
                        value={cronConfig}
                        onChange={(event) => setCronConfig(event.target.value)}
                        rows={8}
                        className="min-h-[180px] font-mono text-xs"
                      />
                    </label>
                  ) : null}
                </div>
              </section>
            </div>

            <div className="shrink-0 bg-card px-8 pb-6 pt-3">
              <div className="flex items-center justify-end gap-2 rounded-lg border border-border/60 bg-background/70 px-4 py-3 shadow-sm">
                <Button type="button" variant="ghost" size="sm" onClick={onClose}>
                  {t('tasks.scheduled.actions.cancelEdit')}
                </Button>
                <Button type="button" size="sm" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? <LoadingSpinner className="mr-2 h-3.5 w-3.5" /> : null}
                  {t('tasks.scheduled.actions.save')}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};
