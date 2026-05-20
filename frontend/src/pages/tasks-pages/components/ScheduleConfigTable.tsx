import React from 'react';
import { useTranslation } from 'react-i18next';
import { Info, Pencil, Play, Power, PowerOff, Settings, Trash2 } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import type { ScheduleDTO } from '@/api';
import {
  getScheduleTargetLabelKey,
  getScheduleTargetLabelFallback,
  getScheduleTitle,
} from '../utils/scheduleHelpers';
import {
  formatScheduleTableTime,
  getScheduleTriggerSummary,
} from '../utils/scheduleFormatters';
import { IconActionButton } from './IconActionButton';

export interface ScheduleGroup {
  pluginId: string;
  label: string;
  rows: ScheduleDTO[];
}

export interface ScheduleConfigTableProps {
  schedules: ScheduleDTO[];
  groups?: ScheduleGroup[];
  loading: boolean;
  emptyMessage: string;
  editingScheduleId: string | null;
  runningScheduleId: string | null;
  togglingScheduleId: string | null;
  deletingScheduleId: string | null;
  onSelectSchedule: (s: ScheduleDTO) => void;
  onRunSchedule: (s: ScheduleDTO) => void;
  onToggleSchedule: (s: ScheduleDTO) => void;
  onDeleteSchedule: (s: ScheduleDTO) => void;
  onOpenSettings: (s: ScheduleDTO) => void;
  onOpenInfo: (s: ScheduleDTO) => void;
}

export const ScheduleConfigTable: React.FC<ScheduleConfigTableProps> = (props) => {
  const { t } = useTranslation('app');
  const {
    schedules, groups, loading, emptyMessage,
    editingScheduleId, runningScheduleId, togglingScheduleId, deletingScheduleId,
    onSelectSchedule, onRunSchedule, onToggleSchedule, onDeleteSchedule,
    onOpenSettings, onOpenInfo,
  } = props;

  const renderRow = (schedule: ScheduleDTO): React.ReactElement => {
    const sensorOwned = schedule.target_type === 'sensor_sync';
    const systemOwned = schedule.editable === false && !sensorOwned;
    const selected = editingScheduleId === schedule.schedule_id;
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
          !sensorOwned && !systemOwned && 'cursor-pointer',
        )}
        onClick={() => { if (!sensorOwned && !systemOwned) onSelectSchedule(schedule); }}
      >
        <td className="px-4 py-3 align-middle">
          <div className="flex items-center gap-2">
            <div className="truncate font-medium text-foreground" title={getScheduleTitle(schedule)}>
              {getScheduleTitle(schedule)}
            </div>
            {!schedule.enabled ? (
              <span className="rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-[10px] uppercase tracking-wide">
                {t('tasks.scheduled.status.disabled')}
              </span>
            ) : null}
            {scheduleRunning ? (
              <span className="rounded-full bg-emerald-500/15 text-emerald-500 px-2 py-0.5 text-[10px] uppercase tracking-wide">
                {t('tasks.scheduled.status.running')}
              </span>
            ) : null}
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
              icon={runPending ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              onClick={(e) => { e.stopPropagation(); onRunSchedule(schedule); }}
            />
            {!sensorOwned && !systemOwned ? (
              <IconActionButton
                variant="outline"
                label={t('tasks.scheduled.actions.edit')}
                icon={<Pencil className="h-3.5 w-3.5" />}
                disabled={rowBusy}
                onClick={(e) => { e.stopPropagation(); onSelectSchedule(schedule); }}
              />
            ) : null}
            {sensorOwned ? (
              <IconActionButton
                variant="secondary"
                label={t('tasks.scheduled.actions.openSettings')}
                icon={<Settings className="h-3.5 w-3.5" />}
                disabled={rowBusy}
                onClick={(e) => { e.stopPropagation(); onOpenSettings(schedule); }}
              />
            ) : null}
            {systemOwned ? (
              <IconActionButton
                variant="secondary"
                label={t('tasks.scheduled.actions.openInfo')}
                icon={<Info className="h-3.5 w-3.5" />}
                disabled={rowBusy}
                onClick={(e) => { e.stopPropagation(); onOpenInfo(schedule); }}
              />
            ) : null}
            <IconActionButton
              variant="outline"
              label={toggleLabel}
              disabled={rowBusy || scheduleRunning}
              icon={togglePending ? <LoadingSpinner className="h-3.5 w-3.5" /> : (
                schedule.enabled ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />
              )}
              onClick={(e) => { e.stopPropagation(); onToggleSchedule(schedule); }}
            />
            {!sensorOwned && !systemOwned ? (
              <IconActionButton
                variant="ghost"
                label={t('tasks.scheduled.actions.delete')}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                disabled={rowBusy || scheduleRunning}
                icon={deletePending ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Trash2 className="h-3.5 w-3.5" />}
                onClick={(e) => { e.stopPropagation(); onDeleteSchedule(schedule); }}
              />
            ) : null}
          </div>
        </td>
      </tr>
    );
  };

  return (
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
          {groups ? (
            groups.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-xs text-muted-foreground">{emptyMessage}</td>
              </tr>
            ) : (
              groups.map((group) => (
                <React.Fragment key={group.pluginId}>
                  <tr className="bg-muted/30">
                    <td colSpan={5} className="px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.label}
                    </td>
                  </tr>
                  {group.rows.map((schedule) => renderRow(schedule))}
                </React.Fragment>
              ))
            )
          ) : !loading && schedules.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-xs text-muted-foreground">{emptyMessage}</td>
            </tr>
          ) : schedules.map((schedule) => renderRow(schedule))}
        </tbody>
      </table>
    </div>
  );
};
