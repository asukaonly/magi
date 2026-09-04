import type { ReactNode } from 'react';
import {
  AlertTriangle,
  Check,
  GitMerge,
  Loader2,
  Pause,
  X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { ProjectedExecutionProgressPresentation } from '@/domain/chat/presentation';

type ExecutionProgressPanelProps = {
  variant: 'card' | 'bubble';
  presentation: ProjectedExecutionProgressPresentation;
  traceEntry?: ReactNode;
  onCancel?: () => void;
  onDetach?: () => void;
};

const PLAN_STEP_STYLE_BY_STATUS = {
  pending: {
    dot: 'bg-muted-foreground/60',
    container: 'border-border/40 bg-background/70',
  },
  running: {
    dot: 'bg-primary',
    container: 'border-primary/30 bg-primary/5',
  },
  completed: {
    dot: 'bg-emerald-500',
    container: 'border-emerald-200 bg-emerald-50/60',
  },
  failed: {
    dot: 'bg-rose-500',
    container: 'border-rose-200 bg-rose-50/70',
  },
} as const;

export const ExecutionProgressPanel = ({
  variant,
  presentation,
  traceEntry,
  onCancel,
  onDetach,
}: ExecutionProgressPanelProps) => {
  const { t } = useTranslation('app');
  const turnId = presentation.turnId;

  if (!turnId) {
    return null;
  }

  const statusTitle = presentation.statusTitle || t(presentation.statusTitleKey);
  const indicator = (() => {
    switch (presentation.indicator) {
      case 'completed':
        return <Check className="h-4 w-4 text-emerald-600" aria-hidden="true" />;
      case 'failed':
        return <X className="h-4 w-4 text-rose-600" aria-hidden="true" />;
      case 'blocked':
        return <AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden="true" />;
      case 'cancelled':
        return <X className="h-4 w-4 text-muted-foreground" aria-hidden="true" />;
      case 'interrupted':
        return <Pause className="h-4 w-4 text-amber-600" aria-hidden="true" />;
      case 'merged':
        return <GitMerge className="h-4 w-4 text-primary" aria-hidden="true" />;
      default:
        return (
          <Loader2
            className={`h-4 w-4 text-primary ${presentation.showSpinningIndicator ? 'animate-spin' : ''}`}
            aria-hidden="true"
          />
        );
    }
  })();
  const shellClassName = variant === 'card'
    ? ''
    : 'mt-3 border-t border-border/35 pt-3';

  return (
    <div className={shellClassName} data-testid={`chat-execution-panel-${turnId}`}>
      {presentation.showBubbleTitle && (
        <div className="flex items-center gap-2">
          {indicator}
          <span className="text-sm font-medium text-foreground">{statusTitle}</span>
        </div>
      )}
      {presentation.showSubtitle && (
        <div className={`${presentation.showBubbleTitle ? 'mt-1' : ''} text-xs leading-5 text-muted-foreground`}>
          {t(presentation.subtitle.key, presentation.subtitle.values)}
        </div>
      )}
      {presentation.planStage && (
        <div className="mt-3 rounded-lg border border-border/50 bg-background/70 px-3 py-2 text-xs font-medium text-foreground/80">
          {t(presentation.planStage.key, presentation.planStage.values)}
        </div>
      )}
      {presentation.traceStats && (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          <span className="rounded-full bg-muted px-2.5 py-1">
            {t('chat.trace.active', { count: presentation.traceStats.activeSteps })}
          </span>
          <span className="rounded-full bg-muted px-2.5 py-1">
            {t('chat.trace.done', { count: presentation.traceStats.completedSteps })}
          </span>
          {presentation.traceStats.failedSteps > 0 && (
            <span className="rounded-full bg-rose-50 px-2.5 py-1 text-rose-600">
              {t('chat.trace.failedCount', { count: presentation.traceStats.failedSteps })}
            </span>
          )}
        </div>
      )}
      {presentation.planSummary && presentation.planSummary.steps.length > 0 && (
        <div className="mt-3 rounded-lg border border-border/50 bg-background/80 p-3">
          <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            <span className="rounded-full bg-muted px-2.5 py-1">
              {presentation.planSummary.parallelMode === 'parallel'
                ? t('chat.trace.plan.parallel')
                : t('chat.trace.plan.sequential')}
            </span>
            <span className="rounded-full bg-muted px-2.5 py-1">
              {t('chat.trace.plan.totalSteps', { count: presentation.planSummary.totalSteps })}
            </span>
          </div>
          <div className="mt-3 space-y-2">
            {presentation.planSummary.steps.map((step) => {
              const stepStyle = PLAN_STEP_STYLE_BY_STATUS[step.status];

              return (
                <div
                  key={step.key}
                  className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2 ${stepStyle.container}`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${stepStyle.dot}`} />
                    <span className="text-sm leading-6 text-foreground">{step.label}</span>
                  </div>
                  <span className="shrink-0 rounded-full bg-background/80 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {t(`chat.trace.plan.stepStatus.${step.status}`)}
                  </span>
                </div>
              );
            })}
          </div>
          {presentation.planSummary.remainingSteps > 0 && (
            <div className="mt-3 text-[11px] text-muted-foreground">
              {t('chat.trace.plan.moreSteps', { count: presentation.planSummary.remainingSteps })}
            </div>
          )}
        </div>
      )}
      {presentation.footer && (
        <div className="mt-3 text-[11px] text-muted-foreground">
          {t(presentation.footer.key, presentation.footer.values)}
        </div>
      )}
      {(traceEntry || presentation.showCancelButton || presentation.showDetachButton) ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {traceEntry}
          {presentation.showCancelButton && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={presentation.isCancelling}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onCancel?.();
              }}
              className="h-7 rounded-full px-2.5 text-[11px]"
            >
              {t('chat.trace.cancelRun')}
            </Button>
          )}
          {presentation.showDetachButton && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={presentation.isDetaching}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onDetach?.();
              }}
              className="h-7 rounded-full px-2.5 text-[11px]"
            >
              {t('chat.trace.detachRun')}
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
};
