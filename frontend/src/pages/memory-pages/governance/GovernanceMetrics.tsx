import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function MetricCell({
  icon,
  label,
  value,
  tone = 'default',
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: 'default' | 'warn' | 'danger';
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 border-[hsl(var(--memory-divider)/0.5)] px-2 py-2 md:border-r md:last:border-r-0">
      <div className={cn(
        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.76)] text-[hsl(var(--memory-accent))]',
        tone === 'warn' && 'bg-amber-50 text-amber-700',
        tone === 'danger' && 'bg-red-50 text-red-700'
      )}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-[hsl(var(--memory-muted))]">{label}</div>
        <div className="mt-0.5 text-lg font-semibold text-[hsl(var(--memory-title))]">{value}</div>
      </div>
    </div>
  );
}
