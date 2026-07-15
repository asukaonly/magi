import React from 'react';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal, Pencil, Power, PowerOff, Settings, Trash2 } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
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
import { ScheduleRunButton } from './ScheduleRunButton';

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
  onRunSchedule: (s: ScheduleDTO, overrideParams?: Record<string, unknown>) => void;
  onToggleSchedule: (s: ScheduleDTO) => void;
  onDeleteSchedule: (s: ScheduleDTO) => void;
  onOpenSettings: (s: ScheduleDTO) => void;
  onOpenInfo: (s: ScheduleDTO) => void;
}

export const ScheduleConfigTable: React.FC<ScheduleConfigTableProps> = (props) => {
  const { t, i18n } = useTranslation('app');
  const locale = i18n?.language;
  const todayLabel = t('tasks.scheduled.filters.window.today');
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
          'transition-colors duration-200',
          selected && 'bg-primary/[0.045]',
          !selected && 'hover:bg-muted/25',
          // Non-sensor rows open a read-only overview. Mutations stay in
          // explicit controls so opening details never changes state.
          !sensorOwned && 'cursor-pointer',
        )}
        onClick={() => { if (!sensorOwned) onOpenInfo(schedule); }}
      >
        <td className="px-4 py-3.5 align-middle">
          <div className="flex items-center gap-2">
            <div className="truncate text-sm font-semibold text-foreground" title={getScheduleTitle(schedule)}>
              {getScheduleTitle(schedule)}
            </div>
            {!schedule.enabled ? (
              <span className="text-[11px] font-medium text-muted-foreground">
                ·{' '}
                {t('tasks.scheduled.status.disabled')}
              </span>
            ) : null}
            {scheduleRunning ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {t('tasks.scheduled.status.running')}
              </span>
            ) : null}
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground" title={scheduleTypeLabel}>
            {scheduleTypeLabel}
          </div>
        </td>
        <td className="px-4 py-3.5 align-middle text-xs font-medium text-foreground" title={triggerText}>{triggerText}</td>
        <td className="whitespace-nowrap px-4 py-3.5 align-middle text-xs tabular-nums text-muted-foreground">{formatScheduleTableTime(schedule.target_state?.last_run_at, locale, todayLabel)}</td>
        <td className="whitespace-nowrap px-4 py-3.5 align-middle text-xs tabular-nums text-muted-foreground">{formatScheduleTableTime(schedule.target_state?.next_run_at, locale, todayLabel)}</td>
        <td className="px-4 py-3.5 align-middle">
          <div className="flex justify-end gap-0.5">
            <ScheduleRunButton
              schedule={schedule}
              disabled={runDisabled}
              pending={runPending}
              onRun={onRunSchedule}
            />
            {sensorOwned ? (
              <IconActionButton
                variant="ghost"
                label={t('tasks.scheduled.actions.openSettings')}
                icon={<Settings className="h-3.5 w-3.5" />}
                disabled={rowBusy}
                onClick={(e) => { e.stopPropagation(); onOpenSettings(schedule); }}
                className="text-muted-foreground hover:text-foreground"
              />
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <IconActionButton
                  variant="ghost"
                  label={t('tasks.scheduled.actions.more')}
                  icon={<MoreHorizontal className="h-4 w-4" />}
                  disabled={rowBusy}
                  onClick={(e) => e.stopPropagation()}
                  className="text-muted-foreground hover:text-foreground"
                />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                {!sensorOwned && !systemOwned ? (
                  <DropdownMenuItem onSelect={() => onSelectSchedule(schedule)}>
                    <Pencil className="h-3.5 w-3.5" />
                    {t('tasks.scheduled.actions.edit')}
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem
                  disabled={rowBusy || scheduleRunning}
                  onSelect={() => onToggleSchedule(schedule)}
                >
                  {togglePending ? <LoadingSpinner className="h-3.5 w-3.5" /> : (
                    schedule.enabled ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />
                  )}
                  {toggleLabel}
                </DropdownMenuItem>
                {!sensorOwned && !systemOwned ? (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      destructive
                      disabled={rowBusy || scheduleRunning}
                      onSelect={() => onDeleteSchedule(schedule)}
                    >
                      {deletePending ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Trash2 className="h-3.5 w-3.5" />}
                      {t('tasks.scheduled.actions.delete')}
                    </DropdownMenuItem>
                  </>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </td>
      </tr>
    );
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="border-b border-border/45 text-xs text-muted-foreground">
          <tr>
            <th className="w-[32%] px-4 py-3 font-semibold">{t('tasks.scheduled.columns.name')}</th>
            <th className="w-[18%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.rule')}</th>
            <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.lastRun')}</th>
            <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.nextRun')}</th>
            <th className="w-[16%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/35">
          {groups ? (
            groups.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-xs text-muted-foreground">{emptyMessage}</td>
              </tr>
            ) : (
              groups.map((group) => (
                <React.Fragment key={group.pluginId}>
                  <tr className="bg-muted/20">
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
