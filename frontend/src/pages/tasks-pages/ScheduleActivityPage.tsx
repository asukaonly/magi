import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { schedulesApi, type ScheduleActivityDTO, type ScheduleDTO } from '@/api';
import { cn } from '@/lib/utils';
import { TasksPageFrame } from './TasksPageFrame';
import { ScheduleActivityTable } from './components/ScheduleActivityTable';
import { ActivityDetailDrawer } from './components/ActivityDetailDrawer';
import { CategoryChipBar, type CategoryFilter } from './components/CategoryChipBar';
import { TasksPaginationBar } from './components/TasksPaginationBar';
import { scheduleCategory } from './utils/scheduleCategory';

const PAGE_SIZE = 50;

type WindowKey = 'today' | 'last24h' | 'last7d';

const windowToSinceSeconds = (key: WindowKey): number => {
  if (key === 'today') {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime() / 1000;
  }
  const now = Date.now() / 1000;
  if (key === 'last24h') return now - 24 * 3600;
  return now - 7 * 24 * 3600;
};

// Status options shown in the filter chip bar. We dropped "upcoming" because
// the backend no longer surfaces upcoming rows on this page (next-run is in
// the schedule config page instead).
const STATUS_OPTIONS = ['running', 'queued', 'succeeded', 'failed', 'cancelled'] as const;
type StatusFilter = 'all' | (typeof STATUS_OPTIONS)[number];
const STATUS_CHIPS: ReadonlyArray<StatusFilter> = ['all', ...STATUS_OPTIONS];

function targetTypesForCategory(category: Exclude<CategoryFilter, 'all' | 'other'>): string[] {
  switch (category) {
    case 'user': return ['user_agent_task'];
    case 'sensor': return ['sensor_sync'];
    case 'memory': return ['memory_l2_maintenance', 'memory_l3_summary', 'memory_l4_maintenance'];
    case 'timeline': return [
      'timeline_diary_narrative',
      'timeline_standout_rescore',
      'timeline_mood_aggregate',
      'timeline_representative_asset',
    ];
  }
}

const EMPTY_COUNTS: Record<CategoryFilter, number> = {
  all: 0, user: 0, sensor: 0, memory: 0, timeline: 0, other: 0,
};

export const ScheduleActivityPage: React.FC = () => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const [windowKey, setWindowKey] = useState<WindowKey>('today');
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [activities, setActivities] = useState<ScheduleActivityDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  // Chip-count aggregations from the server; keyed by raw target_type and
  // by display status. Independent of category/status filters so chip
  // counts stay meaningful when the user filters down.
  const [targetTypeCounts, setTargetTypeCounts] = useState<Record<string, number>>({});
  const [serverStatusCounts, setServerStatusCounts] = useState<Record<string, number>>({});
  const [schedulesById, setSchedulesById] = useState<Record<string, ScheduleDTO>>({});
  const [loading, setLoading] = useState(false);
  const [stoppingActivityId, setStoppingActivityId] = useState<string | null>(null);
  const [selectedActivity, setSelectedActivity] = useState<ScheduleActivityDTO | null>(null);

  // Reset to first page when filters change.
  useEffect(() => {
    setOffset(0);
  }, [windowKey, category, statusFilter]);

  const targetTypes = useMemo(() => {
    if (category === 'all' || category === 'other') return undefined;
    return targetTypesForCategory(category);
  }, [category]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [act, sched] = await Promise.all([
        schedulesApi.listActivity({
          sinceSeconds: windowToSinceSeconds(windowKey),
          limit: PAGE_SIZE,
          offset,
          targetTypes,
          statuses: statusFilter === 'all' ? undefined : [statusFilter],
        }),
        schedulesApi.list({ enabledOnly: false }),
      ]);
      setActivities(act.activities);
      setTotal(act.total ?? 0);
      setTargetTypeCounts(act.target_type_counts ?? {});
      setServerStatusCounts(act.status_counts ?? {});
      setSchedulesById(Object.fromEntries(sched.schedules.map((s) => [s.schedule_id, s])));
    } catch {
      toast.error(t('tasks.scheduled.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [windowKey, targetTypes, statusFilter, offset, t]);

  useEffect(() => { void reload(); }, [reload]);

  // Build category chip counts by bucketing target_type → category, using
  // the server's window-scoped aggregation (so chips reflect the full
  // breakdown even when a chip is already selected).
  const counts = useMemo<Record<CategoryFilter, number>>(() => {
    const next = { ...EMPTY_COUNTS };
    for (const [targetType, n] of Object.entries(targetTypeCounts)) {
      next.all += n;
      const c = scheduleCategory(targetType);
      next[c] = (next[c] ?? 0) + n;
    }
    return next;
  }, [targetTypeCounts]);

  const statusCounts = useMemo<Record<StatusFilter, number>>(() => {
    const next: Record<StatusFilter, number> = {
      all: 0, running: 0, queued: 0, succeeded: 0, failed: 0, cancelled: 0,
    };
    for (const [status, n] of Object.entries(serverStatusCounts)) {
      next.all += n;
      if (status in next) {
        next[status as StatusFilter] = (next[status as StatusFilter] ?? 0) + n;
      }
    }
    return next;
  }, [serverStatusCounts]);

  const handleStop = async (activity: ScheduleActivityDTO) => {
    if (!activity.cancellable) return;
    setStoppingActivityId(activity.activity_id);
    try {
      await schedulesApi.cancelActivity(activity.activity_id);
      toast.success(t('tasks.scheduled.feedback.stopSuccess'));
      await reload();
    } catch {
      toast.error(t('tasks.scheduled.feedback.stopFailed'));
    } finally {
      setStoppingActivityId(null);
    }
  };

  return (
    <TasksPageFrame
      onRefresh={() => void reload()}
      refreshing={loading}
      toolbar={
        <>
          <WindowSegmented value={windowKey} onChange={setWindowKey} />
          <CategoryChipBar value={category} counts={counts} onChange={setCategory} />
          <StatusChipBar value={statusFilter} counts={statusCounts} onChange={setStatusFilter} />
        </>
      }
    >
      <div className="mx-auto w-full max-w-6xl">
        <ScheduleActivityTable
          activities={activities}
          schedulesById={schedulesById}
          emptyMessage={t('tasks.scheduled.empty.activity')}
          stoppingActivityId={stoppingActivityId}
          onStop={handleStop}
          onOpenBackgroundTask={(taskId) => navigate(`/tasks/background?taskId=${encodeURIComponent(taskId)}`)}
          onSelectActivity={setSelectedActivity}
        />
      </div>
      {total > PAGE_SIZE ? (
        <div className="sticky bottom-0 -mx-6 mt-4 border-t border-border/60 bg-background/95 px-6 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <div className="mx-auto w-full max-w-6xl">
            <TasksPaginationBar
              total={total}
              offset={offset}
              limit={PAGE_SIZE}
              loading={loading}
              onPageChange={setOffset}
            />
          </div>
        </div>
      ) : null}
      <ActivityDetailDrawer
        activity={selectedActivity}
        schedulesById={schedulesById}
        onClose={() => setSelectedActivity(null)}
      />
    </TasksPageFrame>
  );
};

const WindowSegmented: React.FC<{ value: WindowKey; onChange: (v: WindowKey) => void }> = ({ value, onChange }) => {
  const { t } = useTranslation('app');
  const options: WindowKey[] = ['today', 'last24h', 'last7d'];
  return (
    <div className="inline-flex rounded-md border border-border/60 p-0.5" role="tablist">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          role="tab"
          aria-selected={value === opt}
          className={`px-2.5 py-1 text-xs font-medium rounded ${value === opt ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted/40'}`}
          onClick={() => onChange(opt)}
        >
          {t(`tasks.scheduled.filters.window.${opt}`)}
        </button>
      ))}
    </div>
  );
};

const StatusChipBar: React.FC<{
  value: StatusFilter;
  counts: Record<StatusFilter, number>;
  onChange: (v: StatusFilter) => void;
}> = ({ value, counts, onChange }) => {
  const { t } = useTranslation('app');
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label={t('tasks.scheduled.columns.status')}>
      {STATUS_CHIPS.map((s) => {
        const active = value === s;
        return (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(s)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              active
                ? 'border-primary/50 bg-primary/10 text-foreground'
                : 'border-border/60 bg-background hover:bg-muted/50 text-muted-foreground',
            )}
          >
            <span>{t(`tasks.scheduled.activityStatus.${s}`)}</span>
            <span className={cn(
              'inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1 text-[10px]',
              active ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground',
            )}>
              {counts[s] ?? 0}
            </span>
          </button>
        );
      })}
    </div>
  );
};
