import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { CalendarClock, ChevronRight, ListChecks, Pencil, RefreshCw, Settings, Square } from 'lucide-react';

import {
  backgroundTasksApi,
  schedulesApi,
  type BackgroundTaskDTO,
  type BackgroundTaskEventDTO,
  type BackgroundTaskStatus,
  type ScheduleActivityDTO,
  type ScheduleDTO,
  type ScheduleTriggerType,
} from '@/api';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import {
  useBackgroundTaskStore,
} from '@/stores/background-tasks';
import { useChatShellStore } from '@/stores';
import { DEFAULT_USER_ID } from '@/constants';
const ACTIVE_STATUSES: ReadonlyArray<BackgroundTaskStatus> = [
  'pending',
  'running',
  'cancelling',
];

type TasksTab = 'background' | 'scheduled';

const SCHEDULE_ACTIVITY_ORDER: Record<string, number> = {
  running: 0,
  queued: 1,
  upcoming: 2,
};

const isActiveStatus = (status: BackgroundTaskStatus): boolean =>
  ACTIVE_STATUSES.includes(status);

const isTerminalStatus = (status: BackgroundTaskStatus): boolean =>
  status === 'succeeded' || status === 'failed' || status === 'cancelled';

const statusToneClass = (status: BackgroundTaskStatus): string => {
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
      return 'bg-sky-500/15 text-sky-500';
    case 'failed':
      return 'bg-red-500/15 text-red-500';
    default:
      return 'bg-muted text-muted-foreground';
  }
};

const formatUnixSeconds = (ts: number | null | undefined): string => {
  if (!ts || !Number.isFinite(ts)) return '—';
  return new Date(ts * 1000).toLocaleString();
};

const formatDuration = (durationMs: number | null | undefined): string => {
  if (!durationMs || !Number.isFinite(durationMs)) return '—';
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
};

const toFiniteNumber = (value: unknown): number | null => {
  const next = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(next) ? next : null;
};

const getSchedulePayloadValue = (schedule: ScheduleDTO, key: string): unknown =>
  schedule.metadata?.[key] ?? schedule.target_payload?.[key];

const getScheduleTitle = (schedule: ScheduleDTO): string => {
  const displayName = getSchedulePayloadValue(schedule, 'display_name')
    ?? getSchedulePayloadValue(schedule, 'title')
    ?? getSchedulePayloadValue(schedule, 'source_type')
    ?? getSchedulePayloadValue(schedule, 'plugin_id');
  return typeof displayName === 'string' && displayName.trim()
    ? displayName
    : schedule.schedule_id;
};

const getActivityTitle = (
  activity: ScheduleActivityDTO,
  schedulesById: Record<string, ScheduleDTO>,
): string => {
  const fromActivity = activity.title?.trim();
  if (fromActivity) return fromActivity;
  const schedule = schedulesById[activity.schedule_id];
  return schedule ? getScheduleTitle(schedule) : activity.schedule_id;
};

const describeScheduleTrigger = (schedule: ScheduleDTO): string => {
  const trigger = schedule.trigger;
  if (trigger.trigger_type === 'interval') {
    const seconds = toFiniteNumber(trigger.config.seconds);
    if (!seconds) return '—';
    return formatDuration(seconds * 1000);
  }
  if (trigger.trigger_type === 'once') {
    return formatUnixSeconds(toFiniteNumber(trigger.config.run_at));
  }
  if (trigger.trigger_type === 'cron') {
    return Object.entries(trigger.config)
      .map(([key, value]) => `${key}=${String(value)}`)
      .join(' ') || 'cron';
  }
  return trigger.trigger_type;
};

const sortActivities = (activities: ScheduleActivityDTO[]): ScheduleActivityDTO[] =>
  [...activities].sort((left, right) => {
    const leftRank = SCHEDULE_ACTIVITY_ORDER[left.status] ?? 9;
    const rightRank = SCHEDULE_ACTIVITY_ORDER[right.status] ?? 9;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return (left.planned_at ?? left.started_at ?? 0) - (right.planned_at ?? right.started_at ?? 0);
  });

interface TaskRowProps {
  task: BackgroundTaskDTO;
  onSelect: (taskId: string) => void;
}

const TaskRow: React.FC<TaskRowProps> = ({ task, onSelect }) => {
  const { t } = useTranslation('app');
  return (
    <button
      type="button"
      onClick={() => onSelect(task.task_id)}
      className="group flex w-full items-center justify-between gap-4 rounded-lg border border-border/60 bg-background/60 px-4 py-3 text-left transition hover:border-border hover:bg-accent/30"
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

interface TasksSectionProps {
  title: string;
  tasks: BackgroundTaskDTO[];
  onSelect: (taskId: string) => void;
}

const TasksSection: React.FC<TasksSectionProps> = ({ title, tasks, onSelect }) => {
  if (tasks.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title} · {tasks.length}
      </h2>
      <div className="space-y-2">
        {tasks.map((task) => (
          <TaskRow key={task.task_id} task={task} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
};

interface TaskDetailDrawerProps {
  taskId: string | null;
  onClose: () => void;
  onMutated: () => void;
}

const TaskDetailDrawer: React.FC<TaskDetailDrawerProps> = ({
  taskId,
  onClose,
  onMutated,
}) => {
  const { t } = useTranslation('app');
  const cachedTask = useBackgroundTaskStore((state) =>
    taskId ? state.tasksById[taskId] : undefined,
  );
  const removeTask = useBackgroundTaskStore((state) => state.remove);
  const upsertTask = useBackgroundTaskStore((state) => state.upsert);

  const [events, setEvents] = useState<BackgroundTaskEventDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionPending, setActionPending] = useState<
    'cancel' | 'retry' | 'dismiss' | null
  >(null);

  useEffect(() => {
    if (!taskId) {
      setEvents([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    backgroundTasksApi
      .get(taskId)
      .then((response) => {
        if (cancelled) return;
        upsertTask(response.task);
        setEvents(response.events);
      })
      .catch(() => {
        if (cancelled) return;
        toast.error(t('tasks.feedback.loadFailed'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, t, upsertTask]);

  const handleCancel = useCallback(async () => {
    if (!taskId) return;
    setActionPending('cancel');
    try {
      const response = await backgroundTasksApi.cancel(taskId);
      if (response.task) upsertTask(response.task);
      toast.success(t('tasks.feedback.cancelSuccess'));
      onMutated();
    } catch {
      toast.error(t('tasks.feedback.cancelFailed'));
    } finally {
      setActionPending(null);
    }
  }, [taskId, t, upsertTask, onMutated]);

  const handleRetry = useCallback(async () => {
    if (!taskId) return;
    setActionPending('retry');
    try {
      const response = await backgroundTasksApi.retry(taskId);
      upsertTask(response.task);
      toast.success(t('tasks.feedback.retrySuccess'));
      onMutated();
    } catch {
      toast.error(t('tasks.feedback.retryFailed'));
    } finally {
      setActionPending(null);
    }
  }, [taskId, t, upsertTask, onMutated]);

  const handleDismiss = useCallback(async () => {
    if (!taskId) return;
    setActionPending('dismiss');
    try {
      await backgroundTasksApi.dismiss(taskId);
      removeTask(taskId);
      toast.success(t('tasks.feedback.dismissSuccess'));
      onClose();
      onMutated();
    } catch {
      toast.error(t('tasks.feedback.dismissFailed'));
    } finally {
      setActionPending(null);
    }
  }, [taskId, t, removeTask, onClose, onMutated]);

  const open = Boolean(taskId);
  const task = cachedTask;

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>
            {task ? task.spec.title || task.spec.goal : t('tasks.page.title')}
          </SheetTitle>
        </SheetHeader>

        {task ? (
          <div className="mt-4 space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  'rounded-full px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide',
                  statusToneClass(task.status),
                )}
              >
                {t(`tasks.status.${task.status}`)}
              </span>
              <span className="text-xs text-muted-foreground">
                {t('tasks.fields.attempt')}: {task.attempt_index + 1}
              </span>
            </div>

            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t('tasks.fields.goal')}
                </dt>
                <dd className="mt-1 whitespace-pre-wrap text-foreground">{task.spec.goal}</dd>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.created')}
                  </dt>
                  <dd>{formatUnixSeconds(task.created_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.started')}
                  </dt>
                  <dd>{formatUnixSeconds(task.started_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.finished')}
                  </dt>
                  <dd>{formatUnixSeconds(task.finished_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.session')}
                  </dt>
                  <dd className="truncate font-mono text-xs">{task.spec.session_id}</dd>
                </div>
              </div>
              {task.spec.selected_tools.length > 0 ? (
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.tools')}
                  </dt>
                  <dd className="mt-1 flex flex-wrap gap-1">
                    {task.spec.selected_tools.map((tool) => (
                      <span
                        key={tool}
                        className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
                      >
                        {tool}
                      </span>
                    ))}
                  </dd>
                </div>
              ) : null}
              {task.summary ? (
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.summary')}
                  </dt>
                  <dd className="mt-1 whitespace-pre-wrap text-foreground">{task.summary}</dd>
                </div>
              ) : null}
              {task.error ? (
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.error')}
                  </dt>
                  <dd className="mt-1 whitespace-pre-wrap text-red-500">{task.error}</dd>
                </div>
              ) : null}
              {task.cancel_reason ? (
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t('tasks.fields.cancelReason')}
                  </dt>
                  <dd className="mt-1 text-foreground">{task.cancel_reason}</dd>
                </div>
              ) : null}
            </dl>

            <div className="flex flex-wrap gap-2">
              {isActiveStatus(task.status) ? (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={actionPending !== null || task.status === 'cancelling'}
                  onClick={handleCancel}
                >
                  {t('tasks.actions.cancel')}
                </Button>
              ) : null}
              {task.status === 'failed' ? (
                <Button
                  variant="default"
                  size="sm"
                  disabled={actionPending !== null}
                  onClick={handleRetry}
                >
                  {t('tasks.actions.retry')}
                </Button>
              ) : null}
              {isTerminalStatus(task.status) ? (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={actionPending !== null}
                  onClick={handleDismiss}
                >
                  {t('tasks.actions.dismiss')}
                </Button>
              ) : null}
            </div>

            <div>
              <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t('tasks.fields.events')}
              </h3>
              <ol className="mt-2 space-y-2">
                {loading ? (
                  <li className="flex items-center gap-2 text-xs text-muted-foreground">
                    <LoadingSpinner className="h-3 w-3" />
                    <span>{t('tasks.page.refreshing')}</span>
                  </li>
                ) : events.length === 0 ? (
                  <li className="text-xs text-muted-foreground">—</li>
                ) : (
                  events.map((event) => (
                    <li
                      key={event.event_id}
                      className="rounded border border-border/60 bg-background/40 p-2 text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-foreground">{event.event_type}</span>
                        <span className="text-muted-foreground">
                          {formatUnixSeconds(event.created_at)}
                        </span>
                      </div>
                      {event.message ? (
                        <p className="mt-1 text-muted-foreground">{event.message}</p>
                      ) : null}
                    </li>
                  ))
                )}
              </ol>
            </div>
          </div>
        ) : (
          <div className="mt-6 flex items-center justify-center">
            <LoadingSpinner className="h-5 w-5" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
};

interface ScheduleEditDrawerProps {
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

const ScheduleEditDrawer: React.FC<ScheduleEditDrawerProps> = ({ schedule, onClose, onSaved }) => {
  const { t } = useTranslation('app');
  const [enabled, setEnabled] = useState(true);
  const [triggerType, setTriggerType] = useState<ScheduleTriggerType>('interval');
  const [intervalSeconds, setIntervalSeconds] = useState('300');
  const [onceRunAt, setOnceRunAt] = useState('');
  const [cronConfig, setCronConfig] = useState('{}');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!schedule) return;
    setEnabled(schedule.enabled);
    setTriggerType(schedule.trigger.trigger_type);
    setIntervalSeconds(String(toFiniteNumber(schedule.trigger.config.seconds) ?? 300));
    setOnceRunAt(secondsToLocalInput(toFiniteNumber(schedule.trigger.config.run_at)));
    setCronConfig(JSON.stringify(schedule.trigger.config || {}, null, 2));
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
    setSaving(true);
    try {
      await schedulesApi.update(schedule.schedule_id, {
        enabled,
        trigger: {
          trigger_type: triggerType,
          config,
        },
      });
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
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{schedule ? getScheduleTitle(schedule) : t('tasks.scheduled.edit.title')}</SheetTitle>
        </SheetHeader>
        {schedule ? (
          <div className="mt-5 space-y-5 text-sm">
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2">
              <span className="font-medium text-foreground">{t('tasks.scheduled.fields.enabled')}</span>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
                className="h-4 w-4 accent-primary"
              />
            </label>
            <label className="block space-y-2">
              <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t('tasks.scheduled.fields.triggerType')}
              </span>
              <select
                value={triggerType}
                onChange={(event) => setTriggerType(event.target.value as ScheduleTriggerType)}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="interval">{t('tasks.scheduled.triggerTypes.interval')}</option>
                <option value="once">{t('tasks.scheduled.triggerTypes.once')}</option>
                <option value="cron">{t('tasks.scheduled.triggerTypes.cron')}</option>
              </select>
            </label>
            {triggerType === 'interval' ? (
              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t('tasks.scheduled.fields.intervalSeconds')}
                </span>
                <input
                  type="number"
                  min={1}
                  value={intervalSeconds}
                  onChange={(event) => setIntervalSeconds(event.target.value)}
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                />
              </label>
            ) : null}
            {triggerType === 'once' ? (
              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t('tasks.scheduled.fields.runAt')}
                </span>
                <input
                  type="datetime-local"
                  value={onceRunAt}
                  onChange={(event) => setOnceRunAt(event.target.value)}
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                />
              </label>
            ) : null}
            {triggerType === 'cron' ? (
              <label className="block space-y-2">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t('tasks.scheduled.fields.cronConfig')}
                </span>
                <textarea
                  value={cronConfig}
                  onChange={(event) => setCronConfig(event.target.value)}
                  rows={8}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
                />
              </label>
            ) : null}
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" size="sm" onClick={onClose}>
                {t('tasks.scheduled.actions.cancelEdit')}
              </Button>
              <Button type="button" size="sm" onClick={() => void handleSave()} disabled={saving}>
                {saving ? <LoadingSpinner className="mr-2 h-3.5 w-3.5" /> : null}
                {t('tasks.scheduled.actions.save')}
              </Button>
            </div>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};

interface ScheduledTasksTabProps {
  refreshToken: number;
  onLoadingChange: (loading: boolean) => void;
  onOpenSettings: (schedule: ScheduleDTO) => void;
}

const ScheduledTasksTab: React.FC<ScheduledTasksTabProps> = ({
  refreshToken,
  onLoadingChange,
  onOpenSettings,
}) => {
  const { t } = useTranslation('app');
  const [schedules, setSchedules] = useState<ScheduleDTO[]>([]);
  const [activities, setActivities] = useState<ScheduleActivityDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleDTO | null>(null);
  const [stoppingActivityId, setStoppingActivityId] = useState<string | null>(null);

  const schedulesById = useMemo(
    () => Object.fromEntries(schedules.map((schedule) => [schedule.schedule_id, schedule])),
    [schedules],
  );

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    onLoadingChange(true);
    try {
      const [scheduleResponse, activityResponse] = await Promise.all([
        schedulesApi.list({ enabledOnly: true }),
        schedulesApi.listActivity({ limit: 100 }),
      ]);
      setSchedules(scheduleResponse.schedules);
      setActivities(sortActivities(activityResponse.activities));
    } catch {
      toast.error(t('tasks.scheduled.feedback.loadFailed'));
    } finally {
      setLoading(false);
      onLoadingChange(false);
    }
  }, [onLoadingChange, t]);

  useEffect(() => {
    void loadSchedules();
  }, [loadSchedules, refreshToken]);

  const handleStopActivity = async (activity: ScheduleActivityDTO) => {
    if (!activity.cancellable) return;
    setStoppingActivityId(activity.activity_id);
    try {
      await schedulesApi.cancelActivity(activity.activity_id);
      toast.success(t('tasks.scheduled.feedback.stopSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.stopFailed'));
    } finally {
      setStoppingActivityId(null);
    }
  };

  const emptySchedules = !loading && schedules.length === 0;
  const emptyActivities = !loading && activities.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">{t('tasks.scheduled.sections.enabled')}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t('tasks.scheduled.sections.enabledHint')}</p>
          </div>
          {loading ? <LoadingSpinner className="h-4 w-4" /> : null}
        </div>
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="min-w-[900px] table-fixed text-left text-sm">
            <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-[24%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
                <th className="w-[14%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.type')}</th>
                <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.rule')}</th>
                <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.lastRun')}</th>
                <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.nextRun')}</th>
                <th className="w-[14%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {emptySchedules ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">
                    {t('tasks.scheduled.empty.enabled')}
                  </td>
                </tr>
              ) : schedules.map((schedule) => {
                const sensorOwned = schedule.target_type === 'sensor_sync' || schedule.editable === false;
                return (
                  <tr key={schedule.schedule_id} className="bg-background/60">
                    <td className="px-4 py-3 align-middle">
                      <div className="truncate font-medium text-foreground">{getScheduleTitle(schedule)}</div>
                      <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{schedule.schedule_id}</div>
                    </td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground">
                      {t(`tasks.scheduled.targetTypes.${schedule.target_type}`, { defaultValue: schedule.target_type })}
                    </td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground">{describeScheduleTrigger(schedule)}</td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground">{formatUnixSeconds(schedule.target_state?.last_run_at)}</td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground">{formatUnixSeconds(schedule.target_state?.next_run_at)}</td>
                    <td className="px-4 py-3 align-middle">
                      <div className="flex justify-end gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={sensorOwned}
                          title={sensorOwned ? t('tasks.scheduled.actions.sensorEditTitle') : undefined}
                          onClick={() => setEditingSchedule(schedule)}
                        >
                          <Pencil className="mr-2 h-3.5 w-3.5" />
                          {t('tasks.scheduled.actions.edit')}
                        </Button>
                        {sensorOwned ? (
                          <Button type="button" variant="secondary" size="sm" onClick={() => onOpenSettings(schedule)}>
                            <Settings className="mr-2 h-3.5 w-3.5" />
                            {t('tasks.scheduled.actions.openSettings')}
                          </Button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">{t('tasks.scheduled.sections.activity')}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t('tasks.scheduled.sections.activityHint')}</p>
        </div>
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="min-w-[900px] table-fixed text-left text-sm">
            <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-[26%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
                <th className="w-[12%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.status')}</th>
                <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.plannedAt')}</th>
                <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.startedAt')}</th>
                <th className="w-[12%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.duration')}</th>
                <th className="w-[16%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {emptyActivities ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">
                    {t('tasks.scheduled.empty.activity')}
                  </td>
                </tr>
              ) : activities.map((activity) => (
                <tr key={activity.activity_id} className="bg-background/60">
                  <td className="px-4 py-3 align-middle">
                    <div className="truncate font-medium text-foreground">{getActivityTitle(activity, schedulesById)}</div>
                    <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{activity.activity_id}</div>
                  </td>
                  <td className="px-4 py-3 align-middle text-xs text-muted-foreground">
                    {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: activity.status })}
                  </td>
                  <td className="px-4 py-3 align-middle text-xs text-muted-foreground">{formatUnixSeconds(activity.planned_at)}</td>
                  <td className="px-4 py-3 align-middle text-xs text-muted-foreground">{formatUnixSeconds(activity.started_at)}</td>
                  <td className="px-4 py-3 align-middle text-xs text-muted-foreground">{formatDuration(activity.duration_ms)}</td>
                  <td className="px-4 py-3 align-middle">
                    <div className="flex justify-end">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={!activity.cancellable || stoppingActivityId === activity.activity_id}
                        title={!activity.cancellable ? t('tasks.scheduled.actions.stopUnavailable') : undefined}
                        onClick={() => void handleStopActivity(activity)}
                      >
                        {stoppingActivityId === activity.activity_id ? (
                          <LoadingSpinner className="mr-2 h-3.5 w-3.5" />
                        ) : (
                          <Square className="mr-2 h-3.5 w-3.5" />
                        )}
                        {t('tasks.scheduled.actions.stop')}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ScheduleEditDrawer
        schedule={editingSchedule}
        onClose={() => setEditingSchedule(null)}
        onSaved={() => void loadSchedules()}
      />
    </div>
  );
};

export const TasksPage: React.FC = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((state) => state.setSettingsNavigationIntent);
  const tasksById = useBackgroundTaskStore((state) => state.tasksById);
  const orderedIds = useBackgroundTaskStore((state) => state.orderedIds);
  const orderedTasks = useMemo(
    () =>
      orderedIds
        .map((id) => tasksById[id])
        .filter((task): task is BackgroundTaskDTO => Boolean(task)),
    [orderedIds, tasksById],
  );
  const hydrate = useBackgroundTaskStore((state) => state.hydrate);
  const [loading, setLoading] = useState(false);
  const [scheduledLoading, setScheduledLoading] = useState(false);
  const [scheduledRefreshToken, setScheduledRefreshToken] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<TasksTab>(
    searchParams.get('tab') === 'scheduled' ? 'scheduled' : 'background',
  );

  useEffect(() => {
    const queryTaskId = searchParams.get('taskId');
    if (queryTaskId && queryTaskId !== selectedTaskId) {
      setActiveTab('background');
      setSelectedTaskId(queryTaskId);
      const next = new URLSearchParams(searchParams);
      next.delete('taskId');
      next.delete('tab');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, selectedTaskId, setSearchParams]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await backgroundTasksApi.list({
        userId: DEFAULT_USER_ID,
        limit: 100,
      });
      hydrate(response.tasks, response.active_count);
    } catch {
      toast.error(t('tasks.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [hydrate, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const { runningTasks, queuedTasks, finishedTasks } = useMemo(() => {
    const running: BackgroundTaskDTO[] = [];
    const queued: BackgroundTaskDTO[] = [];
    const finished: BackgroundTaskDTO[] = [];
    for (const task of orderedTasks) {
      if (task.status === 'running' || task.status === 'cancelling') {
        running.push(task);
      } else if (task.status === 'pending') {
        queued.push(task);
      } else {
        finished.push(task);
      }
    }
    return { runningTasks: running, queuedTasks: queued, finishedTasks: finished };
  }, [orderedTasks]);

  const isEmpty = orderedTasks.length === 0;
  const refreshing = activeTab === 'background' ? loading : scheduledLoading;

  const handleTabChange = (value: string) => {
    const nextTab: TasksTab = value === 'scheduled' ? 'scheduled' : 'background';
    setActiveTab(nextTab);
    const next = new URLSearchParams(searchParams);
    if (nextTab === 'scheduled') {
      next.set('tab', 'scheduled');
    } else {
      next.delete('tab');
    }
    setSearchParams(next, { replace: true });
  };

  const handleRefresh = () => {
    if (activeTab === 'scheduled') {
      setScheduledRefreshToken((value) => value + 1);
      return;
    }
    void refresh();
  };

  const handleOpenScheduleSettings = (schedule: ScheduleDTO) => {
    const sourceName = schedule.settings_link?.source_name;
    if (schedule.settings_link?.section === 'timeline' && sourceName) {
      setSettingsNavigationIntent({ section: 'timeline', source: sourceName });
      setActivePanel('settings');
      return;
    }
    setSettingsNavigationIntent(null);
    setActivePanel('settings');
  };

  return (
    <div className="flex h-full flex-col bg-background">
      <header className="flex items-start justify-between gap-4 border-b border-border/60 px-6 py-5">
        <div>
          <div className="flex items-center gap-2">
            <ListChecks className="h-5 w-5 text-muted-foreground" />
            <h1 className="text-lg font-semibold text-foreground">
              {t('tasks.page.title')}
            </h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t('tasks.page.subtitle')}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          <RefreshCw className={cn('mr-2 h-3.5 w-3.5', refreshing && 'animate-spin')} />
          {refreshing ? t('tasks.page.refreshing') : t('tasks.page.refresh')}
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <Tabs value={activeTab} onValueChange={handleTabChange} className="flex min-h-full flex-col">
          <TabsList className="self-start">
            <TabsTrigger value="background">
              <ListChecks className="mr-2 h-3.5 w-3.5" />
              {t('tasks.tabs.background')}
            </TabsTrigger>
            <TabsTrigger value="scheduled">
              <CalendarClock className="mr-2 h-3.5 w-3.5" />
              {t('tasks.tabs.scheduled')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="background" className="mt-6 flex-1">
            {isEmpty ? (
              <div className="mx-auto flex max-w-md flex-col items-center justify-center rounded-lg border border-dashed border-border/60 px-6 py-16 text-center">
                <ListChecks className="mb-3 h-10 w-10 text-muted-foreground/70" />
                <h2 className="text-sm font-medium text-foreground">
                  {t('tasks.empty.title')}
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t('tasks.empty.description')}
                </p>
              </div>
            ) : (
              <div className="mx-auto max-w-3xl space-y-6">
                <TasksSection
                  title={t('tasks.sections.running')}
                  tasks={runningTasks}
                  onSelect={setSelectedTaskId}
                />
                <TasksSection
                  title={t('tasks.sections.queued')}
                  tasks={queuedTasks}
                  onSelect={setSelectedTaskId}
                />
                <TasksSection
                  title={t('tasks.sections.finished')}
                  tasks={finishedTasks}
                  onSelect={setSelectedTaskId}
                />
              </div>
            )}
          </TabsContent>

          <TabsContent value="scheduled" className="mt-6 flex-1">
            <ScheduledTasksTab
              refreshToken={scheduledRefreshToken}
              onLoadingChange={setScheduledLoading}
              onOpenSettings={handleOpenScheduleSettings}
            />
          </TabsContent>
        </Tabs>
      </div>

      <TaskDetailDrawer
        taskId={selectedTaskId}
        onClose={() => setSelectedTaskId(null)}
        onMutated={refresh}
      />
    </div>
  );
};

export default TasksPage;
