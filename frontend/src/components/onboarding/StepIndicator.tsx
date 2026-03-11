import React from 'react';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StepIndicatorProps {
  steps: string[];
  current: number;
}

export const StepIndicator: React.FC<StepIndicatorProps> = ({ steps, current }) => {
  return (
    <div className="flex flex-col gap-1">
      {steps.map((title, index) => {
        const done = index < current;
        const active = index === current;
        const isLast = index === steps.length - 1;

        return (
          <div key={`${title}-${index}`} className="flex items-stretch">
            {/* Left: number circle + connector line */}
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm font-medium transition-colors',
                  done && 'border-primary bg-primary text-primary-foreground',
                  active && 'border-primary bg-background text-primary',
                  !done && !active && 'border-border bg-background text-muted-foreground'
                )}
              >
                {done ? <Check className="h-4 w-4" /> : index + 1}
              </div>
              {/* Connector line */}
              {!isLast && (
                <div
                  className={cn(
                    'my-1 w-0.5 flex-1 min-h-4',
                    done ? 'bg-primary' : 'bg-border'
                  )}
                />
              )}
            </div>

            {/* Right: step title */}
            <div className="ml-3 pb-4">
              <span
                className={cn(
                  'text-sm leading-8',
                  active ? 'font-medium text-foreground' : done ? 'text-muted-foreground' : 'text-muted-foreground/60'
                )}
              >
                {title}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default StepIndicator;
