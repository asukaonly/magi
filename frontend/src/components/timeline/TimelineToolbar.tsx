import React from 'react';
import { ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-react';
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
    <div className="flex flex-wrap items-center gap-2">
      {/* Scale selector */}
      <div className="flex rounded-lg border border-border/60 p-0.5">
        {SCALE_SEQUENCE.map((item) => (
          <button
            key={item}
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

      {/* Search */}
      <label className="relative min-w-[180px] flex-1">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
        <input
          aria-label={t('timeline.filters.query')}
          value={draftQuery}
          onChange={(e) => onDraftQueryChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onSubmitQuery(); }}
          className="h-8 w-full rounded-lg border border-border/60 bg-transparent pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring/30"
          placeholder={t('timeline.filters.query')}
        />
      </label>

      {/* Nav arrows */}
      <div className="flex items-center gap-0.5">
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onPrevious}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onNext}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Refresh */}
      <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
      </Button>
    </div>
  );
};

export default TimelineToolbar;
