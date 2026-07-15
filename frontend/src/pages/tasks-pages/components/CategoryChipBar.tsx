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
    <div
      className="flex flex-wrap items-center gap-4"
      role="tablist"
      aria-label={t('tasks.scheduled.filters.category')}
    >
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
              'relative inline-flex h-9 items-center gap-1.5 px-0.5 text-sm transition-colors duration-200 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:origin-center after:rounded-sm after:bg-primary after:transition-transform after:duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15',
              active
                ? 'font-semibold text-foreground after:scale-x-100'
                : 'font-medium text-muted-foreground after:scale-x-0 hover:text-foreground',
            )}
          >
            <span>{label}</span>
            <span className={cn('text-[11px] tabular-nums', active ? 'text-primary' : 'text-muted-foreground/70')}>
              {counts[cat] ?? 0}
            </span>
          </button>
        );
      })}
    </div>
  );
};
