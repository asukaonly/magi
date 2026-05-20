import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import {
  backgroundTasksApi,
  type BackgroundTaskEventDTO,
  type BackgroundTaskStatus,
} from '@/api';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { cn } from '@/lib/utils';
import { formatUnixSeconds } from '../utils/scheduleFormatters';
import { statusToneClass } from './BackgroundTaskRow';

const ACTIVE_STATUSES: ReadonlyArray<BackgroundTaskStatus> = [
  'pending',
  'running',
  'cancelling',
];

const isActiveStatus = (status: BackgroundTaskStatus): boolean =>
  ACTIVE_STATUSES.includes(status);

const isTerminalStatus = (status: BackgroundTaskStatus): boolean =>
  status === 'succeeded' || status === 'failed' || status === 'cancelled';

const summarizeExecutionPayload = (
  payload: Record<string, unknown> | null | undefined,
): string => {
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

export interface BackgroundTaskDetailDrawerProps {
  taskId: string | null;
  onClose: () => void;
  onMutated: () => void;
}

export const BackgroundTaskDetailDrawer: React.FC<BackgroundTaskDetailDrawerProps> = ({
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
