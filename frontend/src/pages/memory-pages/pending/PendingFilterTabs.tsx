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
      <div className="inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-lg border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.72)] p-0.5">
        {options.map((option) => {
          const selected = activeFilter === option.key;
          return (
            <button
              key={option.key}
              type="button"
              aria-pressed={selected}
              className={cn(
                'inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium transition-colors',
                selected
                  ? 'bg-[hsl(var(--memory-title))] text-[hsl(var(--memory-panel-elevated))] shadow-sm'
                  : 'text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-subtle)/0.72)]'
              )}
              onClick={() => onChange(option.key)}
            >
              <span>{t(option.labelKey)}</span>
              <span className={cn(
                'text-xs',
                selected ? 'text-[hsl(var(--memory-panel-elevated)/0.82)]' : 'text-[hsl(var(--memory-muted))]'
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
