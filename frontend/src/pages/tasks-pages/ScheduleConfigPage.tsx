import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CalendarClock } from 'lucide-react';

import { schedulesApi, type ScheduleDTO } from '@/api';
import { useChatShellStore } from '@/stores';
import { useSchedulesStore } from '@/stores/schedules';
import { TasksPageFrame } from './TasksPageFrame';
import { ScheduleConfigTable } from './components/ScheduleConfigTable';
import { ScheduleEditDrawer } from './components/ScheduleEditDrawer';

export const ScheduleConfigPage: React.FC = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((s) => s.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((s) => s.setSettingsNavigationIntent);

  const hydrate = useSchedulesStore((s) => s.hydrate);
  const schedules = useSchedulesStore((s) => s.schedules);

  const [loading, setLoading] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleDTO | null>(null);
  const [runningScheduleId, setRunningScheduleId] = useState<string | null>(null);
  const [togglingScheduleId, setTogglingScheduleId] = useState<string | null>(null);
  const [deletingScheduleId, setDeletingScheduleId] = useState<string | null>(null);

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await schedulesApi.list({ enabledOnly: true });
      hydrate(res.schedules);
    } catch {
      toast.error(t('tasks.scheduled.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [hydrate, t]);

  useEffect(() => { void loadSchedules(); }, [loadSchedules]);

  const handleRun = async (s: ScheduleDTO) => {
    if (s.target_state?.running || runningScheduleId) return;
    setRunningScheduleId(s.schedule_id);
    try {
      await schedulesApi.run(s.schedule_id);
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
  const handleOpenInfo = (_s: ScheduleDTO) => {
    // Wired in Task 18.
  };

  return (
    <TasksPageFrame
      title={t('tasks.scheduled.pageTitle')}
      subtitle={t('tasks.scheduled.pageSubtitle')}
      icon={<CalendarClock className="h-5 w-5 text-muted-foreground" />}
      onRefresh={() => void loadSchedules()}
      refreshing={loading}
    >
      <div className="mx-auto flex h-full w-full max-w-6xl flex-col gap-6 overflow-y-auto pr-1">
        <ScheduleConfigTable
          schedules={schedules}
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
          onOpenInfo={handleOpenInfo}
        />
      </div>
      <ScheduleEditDrawer
        schedule={editingSchedule}
        onClose={() => setEditingSchedule(null)}
        onSaved={() => void loadSchedules()}
      />
    </TasksPageFrame>
  );
};
