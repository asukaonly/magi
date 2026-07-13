import { useEffect, useMemo, useState } from 'react';
import { CalendarRange, Check, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

export type SourceBackfillScope = 'last_7_days' | 'last_30_days' | 'full' | 'custom';

export interface SourceBackfillSelection {
  scope: SourceBackfillScope;
  startDate?: string;
  endDate?: string;
}

interface SourceBackfillDialogProps {
  open: boolean;
  sourceLabel: string;
  isSubmitting?: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (selection: SourceBackfillSelection) => Promise<void> | void;
}

const BACKFILL_SCOPE_OPTIONS: SourceBackfillScope[] = ['last_7_days', 'last_30_days', 'custom', 'full'];

const rangeKeyForScope = (scope: SourceBackfillScope) => {
  switch (scope) {
    case 'last_7_days':
      return 'sourceBackfill.ranges.last7Days';
    case 'custom':
      return 'sourceBackfill.ranges.custom';
    case 'full':
      return 'sourceBackfill.ranges.full';
    case 'last_30_days':
    default:
      return 'sourceBackfill.ranges.last30Days';
  }
};

export const SourceBackfillDialog = ({
  open,
  sourceLabel,
  isSubmitting = false,
  onOpenChange,
  onConfirm,
}: SourceBackfillDialogProps) => {
  const { t } = useTranslation('app');
  const [scope, setScope] = useState<SourceBackfillScope>('last_30_days');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const options = useMemo(
    () => BACKFILL_SCOPE_OPTIONS.map((value) => ({
      value,
      label: t(rangeKeyForScope(value)),
    })),
    [t],
  );
  const customRequired = scope === 'custom' && (!startDate || !endDate);
  const customOrderInvalid = scope === 'custom' && Boolean(startDate && endDate && endDate < startDate);
  const customErrorKey = customOrderInvalid
    ? 'sourceBackfill.custom.errorOrder'
    : customRequired
      ? 'sourceBackfill.custom.errorRequired'
      : '';
  const submitDisabled = isSubmitting || customRequired || customOrderInvalid;

  useEffect(() => {
    if (!open) {
      return;
    }
    setScope('last_30_days');
    setStartDate('');
    setEndDate('');
  }, [open]);

  const handleConfirm = () => {
    if (submitDisabled) {
      return;
    }
    if (scope === 'custom') {
      onConfirm({ scope, startDate, endDate });
      return;
    }
    onConfirm({ scope });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[460px] overflow-hidden rounded-lg p-0" hideClose={isSubmitting}>
        <DialogHeader className="border-b border-border/55 bg-background px-5 py-4 pr-12">
          <DialogTitle className="text-base leading-6">{t('sourceBackfill.title')}</DialogTitle>
          <DialogDescription className="mt-1 leading-5">
            {t('sourceBackfill.description', { source: sourceLabel })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 px-5 py-4">
          <div className="space-y-2.5">
            <div className="text-xs font-medium text-muted-foreground">{t('sourceBackfill.rangeLabel')}</div>
            <div
              className="grid grid-cols-2 gap-2"
              role="radiogroup"
              aria-label={t('sourceBackfill.rangeLabel')}
            >
              {options.map((option) => {
                const selected = option.value === scope;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    className={cn(
                      'flex h-11 items-center justify-between gap-3 rounded-md border px-3 text-left text-sm font-medium transition-colors',
                      selected
                        ? 'border-primary/55 bg-primary/10 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.12)]'
                        : 'border-border/65 bg-background text-muted-foreground hover:border-border hover:bg-muted/45 hover:text-foreground',
                    )}
                    disabled={isSubmitting}
                    onClick={() => setScope(option.value)}
                  >
                    <span className="truncate">{option.label}</span>
                    <span
                      className={cn(
                        'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                        selected
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border/80 bg-background text-transparent',
                      )}
                    >
                      <Check className="h-3 w-3" aria-hidden="true" />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          {scope === 'custom' ? (
            <div className="rounded-md border border-border/65 bg-muted/20 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <CalendarRange className="h-3.5 w-3.5" aria-hidden="true" />
                {t('sourceBackfill.custom.title')}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="space-y-1 text-xs font-medium text-muted-foreground">
                  <span>{t('sourceBackfill.custom.start')}</span>
                  <input
                    aria-label={t('sourceBackfill.custom.start')}
                    type="date"
                    value={startDate}
                    disabled={isSubmitting}
                    onChange={(event) => setStartDate(event.target.value)}
                    className="h-9 w-full rounded-md border border-border/70 bg-background px-2.5 text-sm text-foreground outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/15"
                  />
                </label>
                <label className="space-y-1 text-xs font-medium text-muted-foreground">
                  <span>{t('sourceBackfill.custom.end')}</span>
                  <input
                    aria-label={t('sourceBackfill.custom.end')}
                    type="date"
                    value={endDate}
                    disabled={isSubmitting}
                    onChange={(event) => setEndDate(event.target.value)}
                    className="h-9 w-full rounded-md border border-border/70 bg-background px-2.5 text-sm text-foreground outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/15"
                  />
                </label>
              </div>
              {customErrorKey ? (
                <p className="mt-2 text-xs leading-5 text-destructive">{t(customErrorKey)}</p>
              ) : null}
            </div>
          ) : null}
          <p className="text-xs leading-5 text-muted-foreground">
            {t('sourceBackfill.idempotencyNote')}
          </p>
        </div>

        <DialogFooter className="border-t border-border/55 bg-background px-5 py-3">
          <Button
            type="button"
            variant="ghost"
            className="h-9"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
          >
            {t('sourceBackfill.cancel')}
          </Button>
          <Button
            type="button"
            className="h-9"
            onClick={handleConfirm}
            disabled={submitDisabled}
          >
            {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {t('sourceBackfill.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default SourceBackfillDialog;
