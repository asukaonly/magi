import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ChevronRight, ListChecks, RefreshCw } from 'lucide-react';

import {
  backgroundTasksApi,
  type BackgroundTaskDTO,
  type BackgroundTaskEventDTO,
  type BackgroundTaskStatus,
} from '@/api';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import {
  useBackgroundTaskStore,
} from '@/stores/background-tasks';
import { DEFAULT_USER_ID } from '@/constants';
const ACTIVE_STATUSES: ReadonlyArray<BackgroundTaskStatus> = [
  'pending',
  'running',
  'cancelling',
];

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

export const TasksPage: React.FC = () => {
  const { t } = useTranslation('app');
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
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

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
          onClick={() => void refresh()}
          disabled={loading}
        >
          <RefreshCw className={cn('mr-2 h-3.5 w-3.5', loading && 'animate-spin')} />
          {loading ? t('tasks.page.refreshing') : t('tasks.page.refresh')}
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
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
