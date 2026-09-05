import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { ChevronDown } from 'lucide-react';

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
    case 'source': return ['source_sync'];
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
  all: 0, user: 0, source: 0, memory: 0, timeline: 0, other: 0,
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
          <StatusFilterSelect value={statusFilter} counts={statusCounts} onChange={setStatusFilter} />
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
        <div className="sticky bottom-0 -mx-6 mt-4 border-t border-border/35 bg-background/96 px-6 py-2.5 backdrop-blur supports-[backdrop-filter]:bg-background/90">
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
    <div className="inline-flex rounded-lg bg-muted/35 p-1" role="tablist">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          role="tab"
          aria-selected={value === opt}
          className={cn(
            'rounded-md px-2.5 py-1 text-xs font-medium transition-[background-color,color,box-shadow] duration-200',
            value === opt
              ? 'bg-background text-foreground shadow-[0_1px_4px_hsl(var(--foreground)/0.08)]'
              : 'text-muted-foreground hover:text-foreground',
          )}
          onClick={() => onChange(opt)}
        >
          {t(`tasks.scheduled.filters.window.${opt}`)}
        </button>
      ))}
    </div>
  );
};

const StatusFilterSelect: React.FC<{
  value: StatusFilter;
  counts: Record<StatusFilter, number>;
  onChange: (v: StatusFilter) => void;
}> = ({ value, counts, onChange }) => {
  const { t } = useTranslation('app');
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">
        {t('tasks.scheduled.columns.status')}
      </span>
      <div className="relative">
        <select
          value={value}
          aria-label={t('tasks.scheduled.columns.status')}
          onChange={(event) => onChange(event.target.value as StatusFilter)}
          className="h-8 appearance-none rounded-lg border-0 bg-muted/35 pl-3 pr-8 text-xs font-medium text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.45)] outline-none transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-primary/15"
        >
          {STATUS_CHIPS.map((status) => (
            <option key={status} value={status}>
              {t(`tasks.scheduled.activityStatus.${status}`)} · {counts[status] ?? 0}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
      </div>
    </div>
  );
};
