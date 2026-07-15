import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CalendarClock, Plus } from 'lucide-react';

import { schedulesApi, type ScheduleDTO } from '@/api';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useChatShellStore } from '@/stores';
import { useSchedulesStore } from '@/stores/schedules';

import { TasksPageFrame } from './TasksPageFrame';
import { CategoryChipBar, type CategoryFilter } from './components/CategoryChipBar';
import { ScheduleConfigTable, type ScheduleGroup } from './components/ScheduleConfigTable';
import { ScheduleEditDrawer } from './components/ScheduleEditDrawer';
import { ScheduleInfoDrawer } from './components/ScheduleInfoDrawer';
import { scheduleCategory } from './utils/scheduleCategory';
import { getSensorPluginId } from './utils/scheduleHelpers';

const EMPTY_COUNTS: Record<CategoryFilter, number> = {
  all: 0, user: 0, sensor: 0, memory: 0, timeline: 0, other: 0,
};

export const ScheduleConfigPage: React.FC = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((s) => s.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((s) => s.setSettingsNavigationIntent);

  const hydrate = useSchedulesStore((s) => s.hydrate);
  const schedules = useSchedulesStore((s) => s.schedules);

  const [loading, setLoading] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleDTO | null>(null);
  const [creating, setCreating] = useState(false);
  const [infoSchedule, setInfoSchedule] = useState<ScheduleDTO | null>(null);
  const [runningScheduleId, setRunningScheduleId] = useState<string | null>(null);
  const [togglingScheduleId, setTogglingScheduleId] = useState<string | null>(null);
  const [deletingScheduleId, setDeletingScheduleId] = useState<string | null>(null);

  const [category, setCategory] = useState<CategoryFilter>('all');
  const [showDisabled, setShowDisabled] = useState(false);

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await schedulesApi.list({ enabledOnly: !showDisabled });
      hydrate(res.schedules);
    } catch {
      toast.error(t('tasks.scheduled.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [hydrate, showDisabled, t]);

  useEffect(() => { void loadSchedules(); }, [loadSchedules]);

  const counts = useMemo<Record<CategoryFilter, number>>(() => {
    const next = { ...EMPTY_COUNTS };
    for (const s of schedules) {
      next.all += 1;
      const c = scheduleCategory(s.target_type);
      next[c] = (next[c] ?? 0) + 1;
    }
    return next;
  }, [schedules]);

  const filtered = useMemo(() => {
    if (category === 'all') return schedules;
    return schedules.filter((s) => scheduleCategory(s.target_type) === category);
  }, [schedules, category]);

  const sensorGroups = useMemo<ScheduleGroup[] | undefined>(() => {
    if (category !== 'sensor') return undefined;
    const byPlugin = new Map<string, ScheduleDTO[]>();
    for (const s of filtered) {
      const pid = getSensorPluginId(s);
      const list = byPlugin.get(pid) ?? [];
      list.push(s);
      byPlugin.set(pid, list);
    }
    return Array.from(byPlugin.entries()).map(([pluginId, rows]) => ({
      pluginId,
      label: pluginId,
      rows,
    }));
  }, [filtered, category]);

  const handleRun = async (s: ScheduleDTO, overrideParams?: Record<string, unknown>) => {
    if (s.target_state?.running || runningScheduleId) return;
    setRunningScheduleId(s.schedule_id);
    try {
      await schedulesApi.run(s.schedule_id, overrideParams);
      toast.success(t('tasks.scheduled.feedback.runSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.runFailed'));
    } finally { setRunningScheduleId(null); }
  };
  const handleToggle = async (s: ScheduleDTO) => {
    setTogglingScheduleId(s.schedule_id);
    try {
      await schedulesApi.update(s.schedule_id, { enabled: !s.enabled });
      toast.success(t('tasks.scheduled.feedback.toggleSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.toggleFailed'));
    } finally { setTogglingScheduleId(null); }
  };
  const handleDelete = async (s: ScheduleDTO) => {
    setDeletingScheduleId(s.schedule_id);
    try {
      await schedulesApi.remove(s.schedule_id);
      toast.success(t('tasks.scheduled.feedback.deleteSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.deleteFailed'));
    } finally { setDeletingScheduleId(null); }
  };
  const handleOpenSettings = (s: ScheduleDTO) => {
    const sourceName = s.settings_link?.source_name;
    if (s.settings_link?.section === 'timeline' && sourceName) {
      setSettingsNavigationIntent({ section: 'timeline', source: sourceName });
      setActivePanel('settings');
      return;
    }
    setSettingsNavigationIntent(null);
    setActivePanel('settings');
  };

  const showUserCta =
    category === 'user' && !loading && filtered.length === 0;

  return (
    <TasksPageFrame
      onRefresh={() => void loadSchedules()}
      refreshing={loading}
      actions={
        <Button
          size="sm"
          onClick={() => setCreating(true)}
          className="h-9 rounded-lg px-4 shadow-none hover:shadow-none"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          {t('tasks.scheduled.actions.create')}
        </Button>
      }
      toolbar={
        <>
          <CategoryChipBar value={category} counts={counts} onChange={setCategory} />
          <div className="flex items-center gap-2.5 pl-1">
            <Switch
              id="show-disabled-schedules"
              checked={showDisabled}
              onCheckedChange={setShowDisabled}
              aria-label={t('tasks.scheduled.filters.showDisabled')}
              className="h-4 w-7 data-[state=checked]:shadow-none [&>span]:size-3 [&>span]:data-[state=checked]:translate-x-[14px]"
            />
            <label
              htmlFor="show-disabled-schedules"
              className="cursor-pointer text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              {t('tasks.scheduled.filters.showDisabled')}
            </label>
          </div>
        </>
      }
    >
      <div className="mx-auto w-full max-w-6xl">
        {showUserCta ? (
          <div className="flex min-h-[20rem] flex-col items-center justify-center rounded-lg border border-dashed border-border/60 px-6 py-16 text-center">
            <CalendarClock className="mb-3 h-10 w-10 text-muted-foreground/70" />
            <h2 className="text-sm font-medium text-foreground">{t('tasks.scheduled.empty.userCtaTitle')}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{t('tasks.scheduled.empty.userCtaDescription')}</p>
            <Button size="sm" className="mt-4" onClick={() => setCreating(true)}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              {t('tasks.scheduled.actions.create')}
            </Button>
          </div>
        ) : (
          <ScheduleConfigTable
            schedules={filtered}
            groups={sensorGroups}
            loading={loading}
            emptyMessage={t('tasks.scheduled.empty.enabled')}
            editingScheduleId={editingSchedule?.schedule_id ?? null}
            runningScheduleId={runningScheduleId}
            togglingScheduleId={togglingScheduleId}
            deletingScheduleId={deletingScheduleId}
            onSelectSchedule={setEditingSchedule}
            onRunSchedule={handleRun}
            onToggleSchedule={handleToggle}
            onDeleteSchedule={handleDelete}
            onOpenSettings={handleOpenSettings}
            onOpenInfo={setInfoSchedule}
          />
        )}
      </div>
      <ScheduleEditDrawer
        mode={creating ? 'create' : 'edit'}
        schedule={creating ? null : editingSchedule}
        onClose={() => {
          setCreating(false);
          setEditingSchedule(null);
        }}
        onSaved={() => void loadSchedules()}
      />
      <ScheduleInfoDrawer
        schedule={infoSchedule}
        onClose={() => setInfoSchedule(null)}
      />
    </TasksPageFrame>
  );
};
