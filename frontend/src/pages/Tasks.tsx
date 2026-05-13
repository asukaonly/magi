import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { CalendarClock, ChevronRight, ListChecks, Pencil, Play, Power, PowerOff, RefreshCw, Settings, Square, Trash2 } from 'lucide-react';

import {
  backgroundTasksApi,
  schedulesApi,
  type BackgroundTaskDTO,
  type BackgroundTaskEventDTO,
  type BackgroundTaskStatus,
  type ScheduleActivityDTO,
  type ScheduleDTO,
  type ScheduleTriggerType,
  type UpdateScheduleRequest,
} from '@/api';
import { Button, type ButtonProps } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
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

const BACKGROUND_TASK_PAGE_SIZE = 20;

type TasksTab = 'background' | 'scheduled';

const SCHEDULE_ACTIVITY_ORDER: Record<string, number> = {
  running: 0,
  queued: 1,
  upcoming: 2,
};

const SCHEDULE_ACTIVITY_WINDOW_SECONDS = 60 * 60;

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
      return 'bg-primary/15 text-primary';
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

const formatScheduleTableTime = (ts: number | null | undefined): string => {
  if (!ts || !Number.isFinite(ts)) return '—';
  return new Intl.DateTimeFormat(undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(ts * 1000));
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

const getScheduleStringValue = (schedule: ScheduleDTO, key: string): string => {
  const value = getSchedulePayloadValue(schedule, key);
  return typeof value === 'string' ? value.trim() : '';
};

const getScheduleTitle = (schedule: ScheduleDTO): string => {
  const displayName = getSchedulePayloadValue(schedule, 'display_name')
    ?? getSchedulePayloadValue(schedule, 'title')
    ?? getSchedulePayloadValue(schedule, 'source_type')
    ?? getSchedulePayloadValue(schedule, 'plugin_id');
  return typeof displayName === 'string' && displayName.trim()
    ? displayName
    : schedule.schedule_id;
};

const getScheduleTargetKind = (schedule: ScheduleDTO): string => (
  getScheduleStringValue(schedule, 'target_kind')
  || getScheduleStringValue(schedule, 'kind')
  || schedule.target_type
);

const getScheduleTargetKindLabelKey = (schedule: ScheduleDTO): string => {
  const kind = getScheduleTargetKind(schedule);
  if (schedule.target_type === 'user_agent_task' && kind === 'agent_task') {
    return 'prompt';
  }
  return kind;
};

const getScheduleTargetKindFallback = (schedule: ScheduleDTO): string => (
  getScheduleTargetKindLabelKey(schedule) === 'prompt'
    ? 'Prompt'
    : getScheduleTargetKind(schedule)
);

const getSchedulePrompt = (schedule: ScheduleDTO): string => (
  getScheduleStringValue(schedule, 'prompt')
  || getScheduleStringValue(schedule, 'message')
  || getScheduleStringValue(schedule, 'goal')
);

const isPromptBackedSchedule = (schedule: ScheduleDTO): boolean => (
  schedule.target_type === 'user_agent_task'
  && getScheduleTargetKind(schedule) === 'agent_task'
);

const getScheduleTargetLabelKey = (schedule: ScheduleDTO): string => (
  isPromptBackedSchedule(schedule)
    ? `tasks.scheduled.targetKinds.${getScheduleTargetKindLabelKey(schedule)}`
    : `tasks.scheduled.targetTypes.${schedule.target_type}`
);

const getScheduleTargetLabelFallback = (schedule: ScheduleDTO): string => (
  isPromptBackedSchedule(schedule)
    ? getScheduleTargetKindFallback(schedule)
    : schedule.target_type
);

const getActivityTitle = (
  activity: ScheduleActivityDTO,
  schedulesById: Record<string, ScheduleDTO>,
): string => {
  const fromActivity = activity.title?.trim();
  if (fromActivity) return fromActivity;
  const schedule = schedulesById[activity.schedule_id];
  return schedule ? getScheduleTitle(schedule) : activity.schedule_id;
};

const formatCompactInterval = (seconds: number): string => {
  const remainingStart = Math.max(1, Math.round(seconds));
  const units = [
    ['d', 24 * 60 * 60],
    ['h', 60 * 60],
    ['m', 60],
    ['s', 1],
  ] as const;
  let remaining = remainingStart;
  const parts: string[] = [];

  for (const [suffix, unitSeconds] of units) {
    if (remaining < unitSeconds) continue;
    const value = Math.floor(remaining / unitSeconds);
    remaining %= unitSeconds;
    parts.push(`${value}${suffix}`);
    if (parts.length === 2) break;
  }

  return parts.length > 0 ? parts.join(' ') : `${remainingStart}s`;
};

const toScheduleToken = (value: unknown, fallback: string = '*'): string => {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text ? text : fallback;
};

const formatCronExpression = (config: Record<string, unknown>): string => (
  [
    toScheduleToken(config.second, '0'),
    toScheduleToken(config.minute),
    toScheduleToken(config.hour),
    toScheduleToken(config.day),
    toScheduleToken(config.month),
    toScheduleToken(config.day_of_week),
  ].join(' ')
);

const getScheduleTriggerSummary = (schedule: ScheduleDTO): string => {
  const trigger = schedule.trigger;
  if (trigger.trigger_type === 'interval') {
    const seconds = toFiniteNumber(trigger.config.seconds);
    if (!seconds) return '—';
    return formatCompactInterval(seconds);
  }
  if (trigger.trigger_type === 'once') {
    return formatUnixSeconds(toFiniteNumber(trigger.config.run_at));
  }
  if (trigger.trigger_type === 'cron') {
    return formatCronExpression(trigger.config);
  }
  return trigger.trigger_type;
};

const filterScheduleActivities = (
  activities: ScheduleActivityDTO[],
  nowUnixSeconds: number = Date.now() / 1000,
): ScheduleActivityDTO[] => activities.filter((activity) => {
  if (activity.status === 'running') {
    const runningAnchor = activity.started_at ?? activity.planned_at;
    return runningAnchor == null || runningAnchor >= nowUnixSeconds - SCHEDULE_ACTIVITY_WINDOW_SECONDS;
  }

  const plannedAnchor = activity.planned_at ?? activity.started_at;
  if (plannedAnchor == null) return false;
  return plannedAnchor >= nowUnixSeconds - SCHEDULE_ACTIVITY_WINDOW_SECONDS
    && plannedAnchor <= nowUnixSeconds + SCHEDULE_ACTIVITY_WINDOW_SECONDS;
});

const sortActivities = (activities: ScheduleActivityDTO[]): ScheduleActivityDTO[] =>
  [...activities].sort((left, right) => {
    const leftRank = SCHEDULE_ACTIVITY_ORDER[left.status] ?? 9;
    const rightRank = SCHEDULE_ACTIVITY_ORDER[right.status] ?? 9;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return (left.planned_at ?? left.started_at ?? 0) - (right.planned_at ?? right.started_at ?? 0);
  });

const summarizeExecutionPayload = (payload: Record<string, unknown> | null | undefined): string => {
  if (!payload || Object.keys(payload).length === 0) return '';
  const preview: Record<string, unknown> = {};
  for (const key of ['status', 'iterations', 'failure_reason', 'error_text']) {
    if (payload[key] !== undefined && payload[key] !== null && payload[key] !== '') {
      preview[key] = payload[key];
    }
  }
  const toolFailures = payload.tool_failures;
  if (Array.isArray(toolFailures) && toolFailures.length > 0) {
    preview.tool_failures = toolFailures;
  }
  const attachments = payload.attachments;
  if (Array.isArray(attachments) && attachments.length > 0) {
    preview.attachments = attachments.length;
  }
  return Object.keys(preview).length > 0 ? JSON.stringify(preview, null, 2) : '';
};

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

interface TasksPaginationBarProps {
  total: number;
  offset: number;
  limit: number;
  loading: boolean;
  onPageChange: (offset: number) => void;
}

const TasksPaginationBar: React.FC<TasksPaginationBarProps> = ({
  total,
  offset,
  limit,
  loading,
  onPageChange,
}) => {
  const { t } = useTranslation('app');
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  if (total <= limit && offset === 0) return null;

  const rangeStart = Math.min(offset + 1, total);
  const rangeEnd = Math.min(offset + limit, total);

  return (
    <div className="flex items-center justify-between rounded-lg border border-border/60 bg-background/90 px-4 py-3 shadow-sm">
      <span className="text-sm text-muted-foreground">
        {t('tasks.pagination.info', { from: rangeStart, to: rangeEnd, total })}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!hasPrev || loading}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          {t('tasks.pagination.prev')}
        </Button>
        <span className="min-w-[4.5rem] text-center text-sm text-foreground">
          {currentPage} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={!hasNext || loading}
          onClick={() => onPageChange(offset + limit)}
        >
          {t('tasks.pagination.next')}
        </Button>
      </div>
    </div>
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

interface IconActionButtonProps extends Omit<ButtonProps, 'children' | 'size'> {
  label: string;
  icon: React.ReactNode;
}

const IconActionButton: React.FC<IconActionButtonProps> = ({
  label,
  icon,
  className,
  type = 'button',
  ...props
}) => (
  <Button
    {...props}
    type={type}
    size="icon"
    aria-label={label}
    title={label}
    className={cn('h-8 w-8 shrink-0', className)}
  >
    {icon}
  </Button>
);

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
  const executionPayloadPreview = task ? summarizeExecutionPayload(task.result_payload) : '';

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="flex w-full max-w-none flex-col overflow-hidden sm:max-w-xl lg:max-w-2xl">
        <SheetHeader className="shrink-0 border-b border-border/60 px-8 pb-5 pt-6 pr-12">
          <SheetTitle className="leading-snug">
            {task ? task.spec.title || task.spec.goal : t('tasks.page.title')}
          </SheetTitle>
        </SheetHeader>

        {task ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
            <div className="space-y-5 pb-2 text-sm">
              <section className="rounded-lg border border-border/60 bg-background/80 p-5 shadow-sm">
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
                <dl className="mt-5 grid gap-4 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('tasks.fields.goal')}
                    </dt>
                    <dd className="mt-2 whitespace-pre-wrap leading-6 text-foreground">{task.spec.goal}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('tasks.fields.created')}
                    </dt>
                    <dd className="mt-1 text-foreground">{formatUnixSeconds(task.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('tasks.fields.started')}
                    </dt>
                    <dd className="mt-1 text-foreground">{formatUnixSeconds(task.started_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('tasks.fields.finished')}
                    </dt>
                    <dd className="mt-1 text-foreground">{formatUnixSeconds(task.finished_at)}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('tasks.fields.session')}
                    </dt>
                    <dd className="mt-1 truncate font-mono text-xs text-foreground">{task.spec.session_id}</dd>
                  </div>
                </dl>
              </section>

              {task.spec.selected_tools.length > 0 ? (
                <section className="rounded-lg border border-border/60 bg-background/70 p-5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {t('tasks.fields.tools')}
                  </h3>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {task.spec.selected_tools.map((tool) => (
                      <span
                        key={tool}
                        className="rounded-md border border-border/60 bg-muted/45 px-2 py-1 font-mono text-[11px] text-muted-foreground"
                      >
                        {tool}
                      </span>
                    ))}
                  </div>
                </section>
              ) : null}

              {task.summary ? (
                <section className="rounded-lg border border-border/60 bg-background/70 p-5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {t('tasks.fields.finalOutput')}
                  </h3>
                  <MarkdownBlock className="mt-3 text-foreground">{task.summary}</MarkdownBlock>
                </section>
              ) : null}

              {executionPayloadPreview ? (
                <section className="rounded-lg border border-border/60 bg-background/70 p-5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {t('tasks.fields.executionResult')}
                  </h3>
                  <pre className="mt-3 max-h-52 overflow-auto rounded-md border border-border/60 bg-muted/40 p-3 font-mono text-xs leading-5 text-muted-foreground">
                    {executionPayloadPreview}
                  </pre>
                </section>
              ) : null}

              {task.error ? (
                <section className="rounded-lg border border-red-500/25 bg-red-500/5 p-5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-red-500">
                    {t('tasks.fields.error')}
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-red-500">{task.error}</p>
                </section>
              ) : null}

              {task.cancel_reason ? (
                <section className="rounded-lg border border-border/60 bg-background/70 p-5">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {t('tasks.fields.cancelReason')}
                  </h3>
                  <p className="mt-2 text-sm text-foreground">{task.cancel_reason}</p>
                </section>
              ) : null}

              <section className="rounded-lg border border-border/60 bg-background/70 p-5">
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {t('tasks.fields.events')}
                </h3>
                <ol className="mt-3 space-y-2">
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
                        className="rounded-md border border-border/60 bg-background/60 p-3 text-xs"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium text-foreground">{event.event_type}</span>
                          <span className="shrink-0 text-muted-foreground">
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
              </section>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center px-8 py-6">
            <LoadingSpinner className="h-5 w-5" />
          </div>
        )}

        {task ? (
          <div className="shrink-0 bg-card px-8 pb-6 pt-3">
            <div className="flex flex-wrap justify-end gap-2 rounded-lg border border-border/60 bg-background/70 px-4 py-3 shadow-sm">
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
          </div>
        ) : null}
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

const drawerFieldLabelClass = 'text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground';
const drawerSectionClass = 'rounded-lg border border-border/60 bg-background/70 p-5';

const ScheduleEditDrawer: React.FC<ScheduleEditDrawerProps> = ({ schedule, onClose, onSaved }) => {
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
  const [runningScheduleId, setRunningScheduleId] = useState<string | null>(null);
  const [stoppingActivityId, setStoppingActivityId] = useState<string | null>(null);
  const [togglingScheduleId, setTogglingScheduleId] = useState<string | null>(null);
  const [deletingScheduleId, setDeletingScheduleId] = useState<string | null>(null);

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
      setActivities(sortActivities(filterScheduleActivities(activityResponse.activities)));
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

  const handleRunSchedule = async (schedule: ScheduleDTO) => {
    if (schedule.target_state?.running || runningScheduleId) return;
    setRunningScheduleId(schedule.schedule_id);
    try {
      await schedulesApi.run(schedule.schedule_id);
      toast.success(t('tasks.scheduled.feedback.runSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.runFailed'));
    } finally {
      setRunningScheduleId(null);
    }
  };

  const handleToggleSchedule = async (schedule: ScheduleDTO) => {
    setTogglingScheduleId(schedule.schedule_id);
    try {
      await schedulesApi.update(schedule.schedule_id, { enabled: !schedule.enabled });
      if (editingSchedule?.schedule_id === schedule.schedule_id) {
        setEditingSchedule(null);
      }
      toast.success(t('tasks.scheduled.feedback.toggleSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.toggleFailed'));
    } finally {
      setTogglingScheduleId(null);
    }
  };

  const handleDeleteSchedule = async (schedule: ScheduleDTO) => {
    setDeletingScheduleId(schedule.schedule_id);
    try {
      await schedulesApi.remove(schedule.schedule_id);
      if (editingSchedule?.schedule_id === schedule.schedule_id) {
        setEditingSchedule(null);
      }
      toast.success(t('tasks.scheduled.feedback.deleteSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.deleteFailed'));
    } finally {
      setDeletingScheduleId(null);
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
        <div className="overflow-hidden rounded-lg border border-border/60">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-[32%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
                <th className="w-[18%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.rule')}</th>
                <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.lastRun')}</th>
                <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.nextRun')}</th>
                <th className="w-[16%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {emptySchedules ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-xs text-muted-foreground">
                    {t('tasks.scheduled.empty.enabled')}
                  </td>
                </tr>
              ) : schedules.map((schedule) => {
                const sensorOwned = schedule.target_type === 'sensor_sync' || schedule.editable === false;
                const selected = editingSchedule?.schedule_id === schedule.schedule_id;
                const scheduleRunning = Boolean(schedule.target_state?.running);
                const runPending = runningScheduleId === schedule.schedule_id;
                const togglePending = togglingScheduleId === schedule.schedule_id;
                const deletePending = deletingScheduleId === schedule.schedule_id;
                const rowBusy = togglePending || deletePending;
                const runDisabled = scheduleRunning || runningScheduleId !== null || rowBusy;
                const triggerMode = t(`tasks.scheduled.triggerTypes.${schedule.trigger.trigger_type}`, {
                  defaultValue: schedule.trigger.trigger_type,
                });
                const triggerText = `${triggerMode} ${getScheduleTriggerSummary(schedule)}`.trim();
                const scheduleTypeLabel = t(getScheduleTargetLabelKey(schedule), {
                  defaultValue: getScheduleTargetLabelFallback(schedule),
                });
                const toggleLabel = schedule.enabled
                  ? t('tasks.scheduled.actions.disable')
                  : t('tasks.scheduled.actions.enable');
                return (
                  <tr
                    key={schedule.schedule_id}
                    className={cn(
                      'bg-background/60 transition-colors',
                      selected && 'bg-primary/5',
                      !selected && 'hover:bg-muted/35',
                      !sensorOwned && 'cursor-pointer',
                    )}
                    onClick={() => {
                      if (!sensorOwned) setEditingSchedule(schedule);
                    }}
                  >
                    <td className="px-4 py-3 align-middle">
                      <div className="truncate font-medium text-foreground" title={getScheduleTitle(schedule)}>
                        {getScheduleTitle(schedule)}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-muted-foreground" title={scheduleTypeLabel}>
                        {scheduleTypeLabel}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-middle text-xs text-foreground" title={triggerText}>{triggerText}</td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatScheduleTableTime(schedule.target_state?.last_run_at)}</td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatScheduleTableTime(schedule.target_state?.next_run_at)}</td>
                    <td className="px-4 py-3 align-middle">
                      <div className="flex justify-end gap-1">
                        <IconActionButton
                          variant="outline"
                          disabled={runDisabled}
                          label={t('tasks.scheduled.actions.runNow')}
                          icon={runPending ? (
                            <LoadingSpinner className="h-3.5 w-3.5" />
                          ) : (
                            <Play className="h-3.5 w-3.5" />
                          )}
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleRunSchedule(schedule);
                          }}
                        />
                        {!sensorOwned ? (
                          <IconActionButton
                            variant="outline"
                            label={t('tasks.scheduled.actions.edit')}
                            icon={<Pencil className="h-3.5 w-3.5" />}
                            disabled={rowBusy}
                            onClick={(event) => {
                              event.stopPropagation();
                              setEditingSchedule(schedule);
                            }}
                          />
                        ) : null}
                        {sensorOwned ? (
                          <IconActionButton
                            variant="secondary"
                            label={t('tasks.scheduled.actions.openSettings')}
                            icon={<Settings className="h-3.5 w-3.5" />}
                            disabled={rowBusy}
                            onClick={(event) => {
                              event.stopPropagation();
                              onOpenSettings(schedule);
                            }}
                          />
                        ) : null}
                        {!sensorOwned ? (
                          <IconActionButton
                            variant="outline"
                            label={toggleLabel}
                            disabled={rowBusy || scheduleRunning}
                            icon={togglePending ? (
                              <LoadingSpinner className="h-3.5 w-3.5" />
                            ) : schedule.enabled ? (
                              <PowerOff className="h-3.5 w-3.5" />
                            ) : (
                              <Power className="h-3.5 w-3.5" />
                            )}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleToggleSchedule(schedule);
                            }}
                          />
                        ) : null}
                        {!sensorOwned ? (
                          <IconActionButton
                            variant="ghost"
                            label={t('tasks.scheduled.actions.delete')}
                            className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                            disabled={rowBusy || scheduleRunning}
                            icon={deletePending ? (
                              <LoadingSpinner className="h-3.5 w-3.5" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleDeleteSchedule(schedule);
                            }}
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
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">{t('tasks.scheduled.sections.activity')}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t('tasks.scheduled.sections.activityHint')}</p>
        </div>
        <div className="overflow-hidden rounded-lg border border-border/60">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="w-[34%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
                <th className="w-[12%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.status')}</th>
                <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.plannedAt')}</th>
                <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.startedAt')}</th>
                <th className="w-[10%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.duration')}</th>
                <th className="w-[10%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {emptyActivities ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">
                    {t('tasks.scheduled.empty.activity')}
                  </td>
                </tr>
              ) : activities.map((activity) => {
                const linkedSchedule = schedulesById[activity.schedule_id];
                const activityTypeLabel = linkedSchedule
                  ? t(getScheduleTargetLabelKey(linkedSchedule), {
                    defaultValue: getScheduleTargetLabelFallback(linkedSchedule),
                  })
                  : t(`tasks.scheduled.targetTypes.${activity.target_type}`, {
                    defaultValue: activity.target_type,
                  });
                return (
                  <tr key={activity.activity_id} className="bg-background/60">
                    <td className="px-4 py-3 align-middle">
                      <div className="truncate font-medium text-foreground" title={getActivityTitle(activity, schedulesById)}>
                        {getActivityTitle(activity, schedulesById)}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-muted-foreground" title={activityTypeLabel}>
                        {activityTypeLabel}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground">
                      {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: activity.status })}
                    </td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatUnixSeconds(activity.planned_at)}</td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatUnixSeconds(activity.started_at)}</td>
                    <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatDuration(activity.duration_ms)}</td>
                    <td className="px-4 py-3 align-middle">
                      <div className="flex justify-end">
                        <IconActionButton
                          variant="outline"
                          label={t('tasks.scheduled.actions.stop')}
                          disabled={!activity.cancellable || stoppingActivityId === activity.activity_id}
                          icon={stoppingActivityId === activity.activity_id ? (
                            <LoadingSpinner className="h-3.5 w-3.5" />
                          ) : (
                            <Square className="h-3.5 w-3.5" />
                          )}
                          onClick={() => void handleStopActivity(activity)}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
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
  const [backgroundOffset, setBackgroundOffset] = useState(0);
  const [backgroundTotal, setBackgroundTotal] = useState(0);
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
        limit: BACKGROUND_TASK_PAGE_SIZE,
        offset: backgroundOffset,
      });
      if (response.total > 0 && backgroundOffset >= response.total) {
        const fallbackOffset = Math.max(
          0,
          (Math.ceil(response.total / BACKGROUND_TASK_PAGE_SIZE) - 1) * BACKGROUND_TASK_PAGE_SIZE,
        );
        if (fallbackOffset !== backgroundOffset) {
          setBackgroundOffset(fallbackOffset);
          return;
        }
      }
      hydrate(response.tasks, response.active_count);
      setBackgroundTotal(response.total);
    } catch {
      toast.error(t('tasks.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [backgroundOffset, hydrate, t]);

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

  const isEmpty = !loading && backgroundTotal === 0;
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

      <div className="flex-1 overflow-hidden px-6 py-5">
        <Tabs value={activeTab} onValueChange={handleTabChange} className="flex h-full min-h-0 flex-col">
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

          <TabsContent value="background" className="mt-6 min-h-0 flex-1">
            <div className="flex h-full min-h-0 flex-col gap-4">
              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                {isEmpty ? (
                  <div className="flex h-full min-h-[20rem] flex-col items-center justify-center rounded-lg border border-dashed border-border/60 px-6 py-16 text-center">
                    <ListChecks className="mb-3 h-10 w-10 text-muted-foreground/70" />
                    <h2 className="text-sm font-medium text-foreground">
                      {t('tasks.empty.title')}
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t('tasks.empty.description')}
                    </p>
                  </div>
                ) : (
                  <div className="w-full space-y-6 pb-1">
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
              </div>
              <div className="shrink-0">
                <TasksPaginationBar
                  total={backgroundTotal}
                  offset={backgroundOffset}
                  limit={BACKGROUND_TASK_PAGE_SIZE}
                  loading={loading}
                  onPageChange={setBackgroundOffset}
                />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="scheduled" className="mt-6 min-h-0 flex-1 overflow-y-auto pr-1">
            <div className="pb-1">
              <ScheduledTasksTab
                refreshToken={scheduledRefreshToken}
                onLoadingChange={setScheduledLoading}
                onOpenSettings={handleOpenScheduleSettings}
              />
            </div>
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
