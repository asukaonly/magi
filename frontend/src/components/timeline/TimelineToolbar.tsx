import React from 'react';
import { CalendarRange, ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type TimelineScale = 'month' | 'week' | 'day' | 'hour';

interface TimelineToolbarProps {
  scale: TimelineScale;
  draftQuery: string;
  refreshing: boolean;
  onDraftQueryChange: (value: string) => void;
  onSubmitQuery: () => void;
  onScaleChange: (scale: TimelineScale) => void;
  onPrevious: () => void;
  onNext: () => void;
  onRefresh: () => void;
}

const SCALE_SEQUENCE: TimelineScale[] = ['month', 'week', 'day', 'hour'];

export const TimelineToolbar: React.FC<TimelineToolbarProps> = ({
  scale,
  draftQuery,
  refreshing,
  onDraftQueryChange,
  onSubmitQuery,
  onScaleChange,
  onPrevious,
  onNext,
  onRefresh,
}) => {
  const { t } = useTranslation('app');

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {SCALE_SEQUENCE.map((item) => (
          <Button
            key={item}
            variant={scale === item ? 'secondary' : 'outline'}
            size="sm"
            aria-label={t(`timeline.scale.${item}`)}
            onClick={() => onScaleChange(item)}
          >
            {t(`timeline.scale.${item}`)}
          </Button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 border-b border-border/60 pb-4">
        <label className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            aria-label={t('timeline.filters.query')}
            value={draftQuery}
            onChange={(event) => onDraftQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                onSubmitQuery();
              }
            }}
            className="h-10 w-full rounded-xl border border-input bg-background pl-9 pr-3 text-sm"
            placeholder={t('timeline.filters.query')}
          />
        </label>
        <Button variant="outline" size="sm" aria-label={t('timeline.nav.previous')} onClick={onPrevious}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" aria-label={t('timeline.nav.next')} onClick={onNext}>
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" aria-label={t('timeline.actions.refresh')} onClick={onRefresh} disabled={refreshing}>
          <CalendarRange className={cn('mr-2 h-4 w-4', refreshing && 'animate-pulse')} />
          {t('timeline.actions.refresh')}
        </Button>
      </div>
    </>
  );
};

export default TimelineToolbar;
