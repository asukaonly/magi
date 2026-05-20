import React from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { SCHEDULE_CATEGORIES, type ScheduleCategory } from '../utils/scheduleCategory';

export type CategoryFilter = 'all' | ScheduleCategory;

export interface CategoryChipBarProps {
  value: CategoryFilter;
  counts: Record<CategoryFilter, number>;
  onChange: (value: CategoryFilter) => void;
}

export const CATEGORY_CHIPS: ReadonlyArray<CategoryFilter> = ['all', ...SCHEDULE_CATEGORIES];

export const CategoryChipBar: React.FC<CategoryChipBarProps> = ({ value, counts, onChange }) => {
  const { t } = useTranslation('app');
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="tablist">
      {CATEGORY_CHIPS.map((cat) => {
        const active = value === cat;
        const label = t(`tasks.scheduled.categories.${cat}`);
        return (
          <button
            key={cat}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(cat)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
              active
                ? 'border-primary/50 bg-primary/10 text-foreground'
                : 'border-border/60 bg-background hover:bg-muted/50 text-muted-foreground',
            )}
          >
            <span>{label}</span>
            <span className={cn(
              'inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1 text-[10px]',
              active ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground',
            )}>
              {counts[cat] ?? 0}
            </span>
          </button>
        );
      })}
    </div>
  );
};
