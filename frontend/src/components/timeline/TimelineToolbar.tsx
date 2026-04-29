import React from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type TimelineScale = 'month' | 'week' | 'day' | 'hour';

interface TimelineToolbarProps {
  scale: TimelineScale;
  draftQuery: string;
  periodInputType: 'month' | 'week' | 'date' | 'datetime-local';
  periodInputValue: string;
  periodInputMax: string;
  canGoNext: boolean;
  refreshing: boolean;
  onDraftQueryChange: (value: string) => void;
  onSubmitQuery: () => void;
  onPeriodInputChange: (value: string) => void;
  onScaleChange: (scale: TimelineScale) => void;
  onPrevious: () => void;
  onNext: () => void;
  onRefresh: () => void;
}

const SCALE_SEQUENCE: TimelineScale[] = ['month', 'week', 'day', 'hour'];

export const TimelineToolbar: React.FC<TimelineToolbarProps> = ({
  scale,
  draftQuery,
  periodInputType,
  periodInputValue,
  periodInputMax,
  canGoNext,
  refreshing,
  onDraftQueryChange,
  onSubmitQuery,
  onPeriodInputChange,
  onScaleChange,
  onPrevious,
  onNext,
  onRefresh,
}) => {
  const { t } = useTranslation('app');

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <div className="flex rounded-lg border border-border/60 p-0.5">
        {SCALE_SEQUENCE.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={scale === item}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
              scale === item
                ? 'bg-foreground/[0.07] text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => onScaleChange(item)}
          >
            {t(`timeline.scale.${item}`)}
          </button>
        ))}
      </div>

      <div className="flex h-8 items-center rounded-lg border border-border/60 bg-background/70">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 rounded-md p-0"
          onClick={onPrevious}
          aria-label={t('timeline.nav.previous')}
          title={t('timeline.nav.previous')}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <label className="relative h-full border-x border-border/50">
          <span className="sr-only">{t('timeline.period.label')}</span>
          <CalendarDays className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
          <input
            type={periodInputType}
            aria-label={t('timeline.period.label')}
            title={t('timeline.period.label')}
            value={periodInputValue}
            max={periodInputMax}
            step={periodInputType === 'datetime-local' ? 3600 : undefined}
            onChange={(event) => onPeriodInputChange(event.target.value)}
            className="h-full w-[9.5rem] bg-transparent pl-7 pr-2 text-xs text-foreground outline-none [color-scheme:light] sm:w-[10.5rem]"
          />
        </label>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 rounded-md p-0"
          onClick={onNext}
          disabled={!canGoNext}
          aria-label={t('timeline.nav.next')}
          title={t('timeline.nav.next')}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      <form
        className="relative min-w-[180px] flex-1 sm:max-w-[240px]"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmitQuery();
        }}
      >
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
        <input
          aria-label={t('timeline.filters.query')}
          value={draftQuery}
          onChange={(e) => onDraftQueryChange(e.target.value)}
          className="h-8 w-full rounded-lg border border-border/60 bg-transparent pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring/30"
          placeholder={t('timeline.filters.queryInWindow')}
        />
      </form>

      <Button
        variant="ghost"
        size="sm"
        className="h-8 w-8 p-0"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label={t('timeline.nav.refresh')}
        title={t('timeline.nav.refresh')}
      >
        <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
      </Button>
    </div>
  );
};

export default TimelineToolbar;
