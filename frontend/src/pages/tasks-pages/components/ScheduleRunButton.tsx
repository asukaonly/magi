import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Play, Sparkles, Zap } from 'lucide-react';

import { Button, buttonVariants } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import type { ScheduleDTO } from '@/api';
import { cn } from '@/lib/utils';

/**
 * Per-target-type hints for the params dialog. The mechanism is generic
 * (any handler can opt in to ``context.schedule.target_payload``); these
 * hints just nudge the user about what params each known handler honors.
 * Add entries as new handlers grow opt-in payload params.
 */
const PARAM_HINTS_BY_TARGET: Record<string, string> = {
  timeline_diary_narrative:
    '{"days": 7}  // 回填过去 7 天的日记（默认 1）',
  timeline_representative_asset:
    '{"days": 7}  // 只给最近 7 天补代表图（默认扫描一批缺图时间段）',
};

export interface ScheduleRunButtonProps {
  schedule: ScheduleDTO;
  disabled?: boolean;
  pending?: boolean;
  onRun: (s: ScheduleDTO, overrideParams?: Record<string, unknown>) => void;
}

/**
 * Run-action affordance for a single schedule row. Two-tier interaction:
 *
 *   1. Click the ▶ icon → small popover with two choices:
 *        - 立即运行           runs immediately with no overrides
 *        - 带参运行…         opens a dialog for one-shot JSON params
 *
 *   2. The dialog accepts a JSON object that's shallow-merged on top of
 *      the schedule's stored ``target_payload`` for this execution only.
 *      The stored row is not mutated; the next periodic tick uses the
 *      original payload.
 *
 * Encapsulates all state (popover + dialog + params text + validation)
 * so callers stay simple — they just provide ``onRun`` which receives an
 * optional second arg with the parsed params.
 */
export const ScheduleRunButton: React.FC<ScheduleRunButtonProps> = ({
  schedule,
  disabled,
  pending,
  onRun,
}) => {
  const { t } = useTranslation('app');
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [paramsText, setParamsText] = useState('');
  const [paramsError, setParamsError] = useState<string | null>(null);

  const paramHint = PARAM_HINTS_BY_TARGET[schedule.target_type];

  const handleRunNow = () => {
    setPopoverOpen(false);
    onRun(schedule);
  };

  const handleOpenParamsDialog = () => {
    setPopoverOpen(false);
    setParamsText('');
    setParamsError(null);
    setDialogOpen(true);
  };

  const handleRunWithParams = () => {
    const trimmed = paramsText.trim();
    if (!trimmed) {
      // No params entered — treat as 立即运行
      setDialogOpen(false);
      onRun(schedule);
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(trimmed);
    } catch (err: any) {
      setParamsError(err?.message || 'invalid JSON');
      return;
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      setParamsError('params must be a JSON object');
      return;
    }
    setParamsError(null);
    setDialogOpen(false);
    onRun(schedule, parsed);
  };

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverTrigger asChild>
          {/* Native <button> directly inside asChild — Slot merges
              Radix's trigger props (aria-expanded, ref, onClick) cleanly
              with the native element's own attrs (aria-label, title,
              className, type). */}
          <button
            type="button"
            aria-label={t('tasks.scheduled.actions.run', { defaultValue: '运行' })}
            title={t('tasks.scheduled.actions.run', { defaultValue: '运行' })}
            className={cn(
              buttonVariants({ variant: 'ghost', size: 'icon' }),
              'h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground',
            )}
            disabled={disabled}
            onClick={(e) => { e.stopPropagation(); }}
          >
            {pending ? (
              <LoadingSpinner className="h-3.5 w-3.5" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-44 p-1"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={handleRunNow}
            className={cn(
              'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm',
              'hover:bg-foreground/5',
            )}
          >
            <Zap className="h-3.5 w-3.5 text-muted-foreground" />
            {t('tasks.scheduled.actions.runNow')}
          </button>
          <button
            type="button"
            onClick={handleOpenParamsDialog}
            className={cn(
              'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm',
              'hover:bg-foreground/5',
            )}
          >
            <Sparkles className="h-3.5 w-3.5 text-muted-foreground" />
            {t('tasks.scheduled.actions.runWithParamsOpen', { defaultValue: '带参运行…' })}
          </button>
        </PopoverContent>
      </Popover>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {t('tasks.scheduled.actions.runWithParams', { defaultValue: '带参运行' })}
            </DialogTitle>
            <DialogDescription>
              {t('tasks.scheduled.fields.overrideParamsHint', {
                defaultValue: '只影响这一次执行；下次定时触发时仍用原参数。',
              })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            {paramHint ? (
              <div className="font-mono text-[11px] leading-5 text-muted-foreground/80">
                {paramHint}
              </div>
            ) : null}
            <textarea
              value={paramsText}
              onChange={(e) => {
                setParamsText(e.target.value);
                if (paramsError) setParamsError(null);
              }}
              placeholder={paramHint ?? '{}'}
              autoFocus
              className="h-28 w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
            />
            {paramsError ? (
              <div className="text-xs text-red-500">{paramsError}</div>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setDialogOpen(false)}>
              {t('tasks.scheduled.actions.cancel', { defaultValue: '取消' })}
            </Button>
            <Button variant="default" size="sm" onClick={handleRunWithParams}>
              {t('tasks.scheduled.actions.runWithParams', { defaultValue: '带参运行' })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
