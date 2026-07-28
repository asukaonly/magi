import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { ListChecks } from 'lucide-react';

import {
  backgroundTasksApi,
  type BackgroundTaskDTO,
} from '@/api';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { DEFAULT_USER_ID } from '@/constants';
import { TasksPageFrame } from './TasksPageFrame';
import { BackgroundTaskRow } from './components/BackgroundTaskRow';
import { BackgroundTaskDetailDrawer } from './components/BackgroundTaskDetailDrawer';
import { TasksPaginationBar } from './components/TasksPaginationBar';

const BACKGROUND_TASK_PAGE_SIZE = 20;

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
          <BackgroundTaskRow key={task.task_id} task={task} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
};

export const BackgroundTasksPage: React.FC = () => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const tasksById = useBackgroundTaskStore((s) => s.tasksById);
  const orderedIds = useBackgroundTaskStore((s) => s.orderedIds);
  const hydrate = useBackgroundTaskStore((s) => s.hydrate);

  const orderedTasks = useMemo(
    () => orderedIds.map((id) => tasksById[id]).filter((task): task is BackgroundTaskDTO => Boolean(task)),
    [orderedIds, tasksById],
  );

  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // Legacy ?tab=scheduled redirect — moved to /tasks/schedules
  useEffect(() => {
    if (searchParams.get('tab') === 'scheduled') {
      navigate('/tasks/schedules', { replace: true });
    }
  }, [searchParams, navigate]);

  // Honor incoming ?taskId= deep link
  useEffect(() => {
    const queryTaskId = searchParams.get('taskId');
    if (queryTaskId && queryTaskId !== selectedTaskId) {
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
        offset,
      });
      if (response.total > 0 && offset >= response.total) {
        const fallbackOffset = Math.max(
          0,
          (Math.ceil(response.total / BACKGROUND_TASK_PAGE_SIZE) - 1) * BACKGROUND_TASK_PAGE_SIZE,
        );
        if (fallbackOffset !== offset) {
          setOffset(fallbackOffset);
          return;
        }
      }
      hydrate(response.tasks, response.active_count);
      setTotal(response.total);
    } catch {
      toast.error(t('tasks.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [offset, hydrate, t]);

  useEffect(() => { void refresh(); }, [refresh]);

  const { running, queued, finished } = useMemo(() => {
    const r: BackgroundTaskDTO[] = [];
    const q: BackgroundTaskDTO[] = [];
    const f: BackgroundTaskDTO[] = [];
    for (const task of orderedTasks) {
      if (task.status === 'running' || task.status === 'cancelling') r.push(task);
      else if (task.status === 'pending') q.push(task);
      else f.push(task);
    }
    return { running: r, queued: q, finished: f };
  }, [orderedTasks]);

  const isEmpty = !loading && total === 0;

  return (
    <TasksPageFrame
      onRefresh={() => void refresh()}
      refreshing={loading}
    >
      <div className="flex flex-col gap-4">
        {isEmpty ? (
          <div className="flex min-h-[20rem] flex-col items-center justify-center rounded-lg border border-dashed border-border/60 px-6 py-16 text-center">
            <ListChecks className="mb-3 h-10 w-10 text-muted-foreground/70" />
            <h2 className="text-sm font-medium text-foreground">{t('tasks.empty.title')}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t('tasks.empty.description')}</p>
          </div>
        ) : (
          <div className="w-full space-y-6 pb-1">
            <TasksSection title={t('tasks.sections.running')} tasks={running} onSelect={setSelectedTaskId} />
            <TasksSection title={t('tasks.sections.queued')} tasks={queued} onSelect={setSelectedTaskId} />
            <TasksSection title={t('tasks.sections.finished')} tasks={finished} onSelect={setSelectedTaskId} />
          </div>
        )}
        <TasksPaginationBar
          total={total}
          offset={offset}
          limit={BACKGROUND_TASK_PAGE_SIZE}
          loading={loading}
          onPageChange={setOffset}
        />
      </div>
      <BackgroundTaskDetailDrawer
        taskId={selectedTaskId}
        onClose={() => setSelectedTaskId(null)}
        onMutated={refresh}
      />
    </TasksPageFrame>
  );
};
