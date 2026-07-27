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
    <div className="flex min-w-0 flex-wrap items-center gap-5">
      {options.map((option) => {
        const selected = activeFilter === option.key;
        return (
          <button
            key={option.key}
            type="button"
            aria-pressed={selected}
            className={cn(
              'relative inline-flex h-10 items-center whitespace-nowrap px-0.5 text-sm transition-colors after:absolute after:inset-x-0 after:bottom-[-1px] after:h-0.5 after:origin-center after:rounded-sm after:bg-[hsl(var(--memory-accent))] after:transition-transform after:duration-200',
              selected
                ? 'font-semibold text-[hsl(var(--memory-title))] after:scale-x-100'
                : 'font-medium text-[hsl(var(--memory-muted))] after:scale-x-0 hover:text-[hsl(var(--memory-title))]'
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
          </button>
        );
      })}
    </div>
  );
}
