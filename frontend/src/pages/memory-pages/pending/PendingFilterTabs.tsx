import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { PendingFilter, PendingFilterOption } from './pendingModel';

export function PendingFilterTabs({
  options,
  activeFilter,
  onChange,
}: {
  options: PendingFilterOption[];
  activeFilter: PendingFilter;
  onChange: (filter: PendingFilter) => void;
}) {
  const { t } = useTranslation('app');

  return (
    <div className="flex">
      <div className="inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-mem-md bg-[hsl(var(--memory-panel-subtle)/0.5)] p-1">
        {options.map((option) => {
          const selected = activeFilter === option.key;
          return (
            <button
              key={option.key}
              type="button"
              aria-pressed={selected}
              className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded-mem-sm px-3 text-sm font-medium transition-colors duration-200',
                selected
                  ? 'bg-[hsl(var(--memory-panel-elevated))] text-[hsl(var(--memory-title))] shadow-sm'
                  : 'text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-elevated)/0.55)] hover:text-[hsl(var(--memory-title))]'
              )}
              onClick={() => onChange(option.key)}
            >
              <span>{t(option.labelKey)}</span>
              <span className={cn(
                'text-xs tabular-nums',
                selected ? 'text-[hsl(var(--memory-body))]' : 'text-[hsl(var(--memory-muted))]'
              )}>
                {option.count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
