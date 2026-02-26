import React from 'react';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StepIndicatorProps {
  steps: string[];
  current: number;
}

export const StepIndicator: React.FC<StepIndicatorProps> = ({ steps, current }) => {
  const progress = steps.length > 1 ? (current / (steps.length - 1)) * 100 : 100;

  return (
    <div className="mb-6 rounded-xl border border-border/80 bg-muted/20 p-3">
      <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-muted/70">
        <div
          className="h-full rounded-full bg-teal-600 transition-all duration-300"
          style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {steps.map((title, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <div
              key={`${title}-${index}`}
              className={cn(
                'inline-flex min-w-fit items-center gap-2 rounded-full border px-3 py-1.5',
                done && 'border-teal-600/20 bg-teal-600/10',
                active && 'border-teal-600/40 bg-teal-600/10',
                !done && !active && 'border-border/80 bg-background'
              )}
            >
              <div
                className={cn(
                  'flex h-5 w-5 items-center justify-center rounded-full border text-[11px]',
                  done && 'border-teal-600 bg-teal-600 text-white',
                  active && 'border-teal-600 text-teal-700',
                  !done && !active && 'border-muted-foreground/40 text-muted-foreground'
                )}
              >
                {done ? <Check className="h-3.5 w-3.5" /> : index + 1}
              </div>
              <span
                className={cn(
                  'text-xs whitespace-nowrap',
                  active ? 'font-medium text-foreground' : 'text-muted-foreground'
                )}
              >
                {title}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default StepIndicator;
