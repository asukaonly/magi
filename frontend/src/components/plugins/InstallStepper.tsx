import { useReducedMotion } from 'framer-motion';
import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';

import type { InstallStep, InstallStepId, StepStatus } from '@/hooks/usePluginInstallFlow';
import { cn } from '@/lib/utils';

export interface InstallStepperProps {
  steps: InstallStep[];
  labels: Record<InstallStepId, string>;
  details?: Partial<Record<InstallStepId, string>>;
}

const statusIconClassName = 'h-4 w-4 shrink-0';

const statusIcon = (status: StepStatus, shouldReduceMotion: boolean) => {
  if (status === 'done') {
    return <CheckCircle2 className={cn(statusIconClassName, 'text-primary')} />;
  }
  if (status === 'running') {
    return (
      <Loader2
        className={cn(statusIconClassName, 'text-primary', !shouldReduceMotion && 'animate-spin')}
      />
    );
  }
  if (status === 'background') {
    return (
      <Loader2
        className={cn(statusIconClassName, 'text-primary', !shouldReduceMotion && 'animate-spin')}
      />
    );
  }
  if (status === 'error') {
    return <XCircle className={cn(statusIconClassName, 'text-destructive')} />;
  }
  return <Circle className={cn(statusIconClassName, 'text-muted-foreground/45')} />;
};

const progressValue = (steps: InstallStep[]): number => {
  if (steps.length === 0) return 0;
  const doneCount = steps.filter((step) => step.status === 'done' || step.status === 'skipped').length;
  const hasRunning = steps.some((step) => step.status === 'running' || step.status === 'background');
  return Math.min(100, Math.round(((doneCount + (hasRunning ? 0.45 : 0)) / steps.length) * 100));
};

export function InstallStepper({ steps, labels, details = {} }: InstallStepperProps) {
  const shouldReduceMotion = useReducedMotion() ?? false;
  const activeStep =
    steps.find((step) => step.status === 'running' || step.status === 'background' || step.status === 'error') ??
    [...steps].reverse().find((step) => step.status === 'done' || step.status === 'skipped') ??
    steps[0];
  const value = progressValue(steps);
  const isBusy = steps.some((step) => step.status === 'running' || step.status === 'background');

  if (steps.length === 0) {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="mt-2 overflow-hidden rounded-lg border border-border/50 bg-background/80 p-4 shadow-[0_10px_28px_hsl(var(--foreground)/0.04)]"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            {isBusy ? (
              <span
                className={cn(
                  'h-2 w-2 rounded-full bg-primary',
                  !shouldReduceMotion && 'animate-pulse',
                )}
                aria-hidden
              />
            ) : null}
            <span className="truncate">{activeStep ? labels[activeStep.id] : ''}</span>
          </div>
          {activeStep && details[activeStep.id] ? (
            <p className="mt-1 text-xs text-muted-foreground">{details[activeStep.id]}</p>
          ) : null}
        </div>
        <div className="shrink-0 text-xs tabular-nums text-muted-foreground">{value}%</div>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-label={activeStep ? labels[activeStep.id] : undefined}
        className="relative mt-3 h-3 overflow-hidden rounded-full bg-primary/10 shadow-inner ring-1 ring-primary/15"
      >
        <div
          className={cn(
            'h-full rounded-full bg-gradient-to-r from-primary/80 via-primary to-primary/90 transition-all duration-500',
            isBusy && !shouldReduceMotion && 'animate-pulse',
          )}
          style={{ width: `${value}%` }}
        />
        {isBusy && !shouldReduceMotion ? (
          <div
            aria-hidden
            className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-primary/35 blur-[1px]"
            style={{ animation: 'install-progress-sweep 1.5s ease-in-out infinite' }}
          />
        ) : null}
      </div>

      <ul className="mt-3 space-y-1">
        {steps.map((step) => {
          const isRunning = step.status === 'running' || step.status === 'background';
          const isDone = step.status === 'done' || step.status === 'skipped';
          const isError = step.status === 'error';
          return (
            <li
              key={step.id}
              data-testid={`step-${step.id}`}
              aria-current={isRunning ? 'step' : undefined}
              className={cn(
                'flex items-start gap-3 rounded-md px-2.5 py-2 text-sm transition-colors duration-300',
                isRunning && 'bg-primary/5 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.12)]',
                isDone && 'text-foreground',
                isError && 'bg-destructive/5 text-destructive',
                !isRunning && !isDone && !isError && 'text-muted-foreground',
              )}
            >
              <span
                aria-hidden
                data-testid={`step-${step.id}-status`}
                data-status={step.status}
                className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center"
              >
                {statusIcon(step.status, shouldReduceMotion)}
              </span>
              <span className="min-w-0">
                <span className={cn('block truncate', isRunning && 'font-medium')}>
                  {labels[step.id]}
                </span>
                {details[step.id] ? (
                  <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                    {details[step.id]}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
