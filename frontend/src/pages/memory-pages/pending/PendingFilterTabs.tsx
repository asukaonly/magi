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
    <div className="flex items-center gap-6">
      {options.map((option) => {
        const selected = activeFilter === option.key;
        return (
          <button
            key={option.key}
            type="button"
            aria-pressed={selected}
            className={cn(
              'group relative pb-2.5 pt-1 text-sm transition-colors duration-200',
              selected
                ? 'font-medium text-[hsl(var(--memory-title))]'
                : 'text-[hsl(var(--memory-muted))] hover:text-[hsl(var(--memory-body))]'
            )}
            onClick={() => onChange(option.key)}
          >
            <span>{t(option.labelKey)}</span>
            <span className={cn(
              'ml-1.5 text-xs tabular-nums',
              selected ? 'text-[hsl(var(--memory-body))]' : 'text-[hsl(var(--memory-muted)/0.8)]'
            )}>
              {option.count}
            </span>
            <span
              aria-hidden="true"
              className={cn(
                'absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-[hsl(var(--memory-accent))] transition-opacity duration-200',
                selected ? 'opacity-100' : 'opacity-0'
              )}
            />
          </button>
        );
      })}
    </div>
  );
}
