import { isRecord } from '@/utils/value-guards';
import React, { useRef, useState } from 'react';
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
  timeline_diary_narrative: 'tasks.scheduled.runParameters.diaryHint',
  timeline_representative_asset: 'tasks.scheduled.runParameters.assetHint',
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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [paramsText, setParamsText] = useState('');
  const [paramsError, setParamsError] = useState<string | null>(null);

  const paramHintKey = PARAM_HINTS_BY_TARGET[schedule.target_type];
  const paramHint = paramHintKey ? t(paramHintKey) : undefined;

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
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      setParamsError(t('tasks.scheduled.runParameters.invalidJson'));
      return;
    }
    if (!isRecord(parsed)) {
      setParamsError(t('tasks.scheduled.runParameters.objectRequired'));
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
            ref={triggerRef}
            type="button"
            aria-label={t('tasks.scheduled.actions.runNow')}
            title={t('tasks.scheduled.actions.runNow')}
            className={cn(
              buttonVariants({ variant: 'ghost', size: 'icon' }),
              'h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground',
            )}
            disabled={disabled || pending}
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
          onCloseAutoFocus={(event) => { if (dialogOpen) event.preventDefault(); }}
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
            {t('tasks.scheduled.runParameters.open')}
          </button>
        </PopoverContent>
      </Popover>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md" onCloseAutoFocus={(event) => { event.preventDefault(); triggerRef.current?.focus(); }}>
          <DialogHeader>
            <DialogTitle>
              {t('tasks.scheduled.runParameters.title')}
            </DialogTitle>
            <DialogDescription>
              {t('tasks.scheduled.runParameters.hint')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            {paramHint ? (
              <div className="font-mono text-[11px] leading-5 text-muted-foreground/80">
                {paramHint}
              </div>
            ) : null}
            <label htmlFor={`schedule-params-${schedule.schedule_id}`} className="sr-only">{t('tasks.scheduled.runParameters.label')}</label>
            <textarea
              id={`schedule-params-${schedule.schedule_id}`}
              aria-invalid={Boolean(paramsError)}
              aria-describedby={paramsError ? `schedule-params-error-${schedule.schedule_id}` : undefined}
              value={paramsText}
              onChange={(e) => {
                setParamsText(e.target.value);
                if (paramsError) setParamsError(null);
              }}
              placeholder={'{}'}
              autoFocus
              className="h-28 w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-xs"
            />
            {paramsError ? (
              <div role="alert" id={`schedule-params-error-${schedule.schedule_id}`} className="text-xs text-destructive">{paramsError}</div>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="default" size="sm" disabled={disabled || pending} onClick={handleRunWithParams}>
              {t('tasks.scheduled.runParameters.title')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
