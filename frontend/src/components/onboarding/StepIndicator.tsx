import React from 'react';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StepIndicatorProps {
  steps: string[];
  current: number;
}

export const StepIndicator: React.FC<StepIndicatorProps> = ({ steps, current }) => {
  return (
    <div className="mb-6">
      <div className="grid gap-2 md:grid-cols-[repeat(auto-fit,minmax(120px,1fr))]">
        {steps.map((title, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <div key={`${title}-${index}`} className="flex items-center gap-2">
              <div
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border text-xs',
                  done && 'border-teal-600 bg-teal-600 text-white',
                  active && 'border-teal-600 text-teal-700',
                  !done && !active && 'border-muted-foreground/40 text-muted-foreground'
                )}
              >
                {done ? <Check className="h-3.5 w-3.5" /> : index + 1}
              </div>
              <span
                className={cn(
                  'text-xs',
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
