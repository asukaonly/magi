import React from 'react';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StepIndicatorProps {
  steps: string[];
  current: number;
}

export const StepIndicator: React.FC<StepIndicatorProps> = ({ steps, current }) => {
  return (
    <ol className="space-y-1">
      {steps.map((title, index) => {
        const done = index < current;
        const active = index === current;

        return (
          <li
            key={`${title}-${index}`}
            aria-current={active ? 'step' : undefined}
            className={cn(
              'flex min-h-11 items-center gap-3 rounded-xl px-3 transition-colors duration-200',
              active ? 'bg-accent/70 text-foreground' : 'text-muted-foreground',
              !done && !active && 'text-muted-foreground/55',
            )}
          >
            <span
              className={cn(
                'flex w-5 shrink-0 items-center justify-center text-[0.68rem] font-semibold tabular-nums',
                active && 'text-primary',
                done && 'text-muted-foreground',
              )}
            >
              {done ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : String(index + 1).padStart(2, '0')}
            </span>
            <span className={cn('text-sm', active && 'font-semibold')}>{title}</span>
          </li>
        );
      })}
    </ol>
  );
};

export default StepIndicator;
