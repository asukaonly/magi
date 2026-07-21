import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StepIndicatorProps {
  steps: string[];
  current: number;
}

export const StepIndicator: React.FC<StepIndicatorProps> = ({ steps, current }) => {
  const shouldReduceMotion = useReducedMotion();

  return (
    <ol className="grid min-w-max grid-cols-4 gap-1 lg:min-w-0 lg:grid-cols-1">
      {steps.map((title, index) => {
        const done = index < current;
        const active = index === current;

        return (
          <li
            key={`${title}-${index}`}
            aria-current={active ? 'step' : undefined}
            className={cn(
              'relative flex min-h-11 min-w-[8.25rem] items-center gap-3 px-3 transition-colors duration-200 motion-reduce:transition-none lg:min-w-0',
              active ? 'text-foreground' : 'text-muted-foreground',
              !done && !active && 'text-muted-foreground/55',
            )}
          >
            {active ? (
              <motion.span
                aria-hidden="true"
                layoutId={shouldReduceMotion ? undefined : 'onboarding-active-step'}
                className="absolute bottom-0 left-3 right-3 h-px bg-primary/70 lg:bottom-2 lg:left-0 lg:right-auto lg:top-2 lg:h-auto lg:w-px"
                transition={{ duration: shouldReduceMotion ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
              />
            ) : null}
            <span
              className={cn(
                'relative flex w-5 shrink-0 items-center justify-center text-[0.68rem] font-semibold tabular-nums',
                active && 'text-primary',
                done && 'text-muted-foreground',
              )}
            >
              {done ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : String(index + 1).padStart(2, '0')}
            </span>
            <span className={cn('relative text-sm', active && 'font-semibold')}>{title}</span>
          </li>
        );
      })}
    </ol>
  );
};

export default StepIndicator;
