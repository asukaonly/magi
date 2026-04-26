import type { ChatTimelineMessage } from './state';
import { shouldShowTraceEntry } from './state';
import type {
  ProjectedExecutionActionState,
  ProjectedExecutionProgressPresentation,
  ProjectedExecutionTranslationDescriptor,
  ProjectedTraceEntryPresentation,
  TurnExecutionControlState,
} from './presentation.types';

type ExecutionActionProjectionInput = {
  executionControlByTurnId: Record<string, TurnExecutionControlState>;
  cancellingTurnIds: string[];
  detachingTurnIds: string[];
};

export type ChatTimelineExecutionProjectionInput = ExecutionActionProjectionInput & {
  summaries: Record<string, { trace_available?: boolean }>;
};

type ProjectedExecutionTranslationValues = Record<string, string | number>;

const normalizeExecutionPlanStepStatus = (
  value: string | null | undefined,
): 'pending' | 'running' | 'completed' | 'failed' => {
  switch (String(value || '').trim().toLowerCase()) {
    case 'running':
    case 'in_progress':
      return 'running';
    case 'completed':
    case 'done':
      return 'completed';
    case 'failed':
    case 'error':
      return 'failed';
    default:
      return 'pending';
  }
};

const createExecutionTranslationDescriptor = (
  key: string,
  values?: ProjectedExecutionTranslationValues,
): ProjectedExecutionTranslationDescriptor => ({
  key,
  values,
});

export const getExecutionActionState = (
  message: ChatTimelineMessage,
  {
    executionControlByTurnId,
    cancellingTurnIds,
    detachingTurnIds,
  }: ExecutionActionProjectionInput,
): ProjectedExecutionActionState => {
  const turnId = String(message.turnId || '').trim();
  const executionControl = turnId ? executionControlByTurnId[turnId] : undefined;
  const traceStatus = String(message.traceSummary?.status || '').trim() || 'running';
  const executionState = executionControl?.state
    || (turnId && detachingTurnIds.includes(turnId) ? 'detaching' : traceStatus);
  const isCancelling = executionState === 'cancelling' || (turnId ? cancellingTurnIds.includes(turnId) : false);
  const isDetaching = executionState === 'detaching' || (turnId ? detachingTurnIds.includes(turnId) : false);

  return {
    turnId,
    executionControl,
    executionState,
    isCancelling,
    isDetaching,
    showCancelButton: Boolean(turnId) && (executionState === 'running' || executionState === 'cancelling'),
    showDetachButton: Boolean(turnId) && executionState === 'running',
  };
};

export const projectTraceEntryPresentation = (
  message: Pick<ChatTimelineMessage, 'turnId' | 'traceDisplayMode' | 'traceAvailable' | 'traceSummary'>,
  summary?: { trace_available?: boolean } | null,
): ProjectedTraceEntryPresentation => {
  const turnId = String(message.turnId || '').trim();
  const traceDisplayMode = String(message.traceDisplayMode || '').trim() || 'collapsible';

  return {
    turnId: turnId || null,
    canOpen: shouldShowTraceEntry(message, summary),
    variant: traceDisplayMode === 'prominent' ? 'prominent' : 'default',
  };
};

export const projectExecutionProgressPresentation = (
  message: ChatTimelineMessage,
  options: ExecutionActionProjectionInput & {
    summary?: { trace_available?: boolean } | null;
    variant?: 'card' | 'bubble';
  },
): ProjectedExecutionProgressPresentation => {
  const executionActionState = getExecutionActionState(message, options);
  const traceEntry = projectTraceEntryPresentation(message, options.summary);
  const variant = options.variant || 'card';
  const turnId = executionActionState.turnId || null;
  const traceSummary = message.traceSummary;
  const planSummary = traceSummary?.planSummary;
  const executionState = executionActionState.executionState;
  const completedSteps = traceSummary?.completedSteps || 0;
  const activeSteps = traceSummary?.activeSteps || 0;
  const failedSteps = traceSummary?.failedSteps || 0;
  const statusTitleKey = (() => {
    switch (executionState) {
      case 'detaching':
        return 'chat.trace.execution.detachingTitle';
      case 'cancelling':
        return 'chat.trace.execution.cancellingTitle';
      case 'cancelled':
        return 'chat.trace.execution.cancelledTitle';
      case 'completed':
        return 'chat.trace.execution.completedTitle';
      case 'failed':
        return 'chat.trace.execution.failedTitle';
      default:
        return 'chat.trace.execution.runningTitle';
    }
  })();
  const subtitle = (() => {
    switch (executionState) {
      case 'detaching':
        return createExecutionTranslationDescriptor('chat.trace.execution.detachingBody');
      case 'cancelling':
        return createExecutionTranslationDescriptor('chat.trace.execution.cancellingBody');
      case 'cancelled':
        return createExecutionTranslationDescriptor('chat.trace.execution.cancelledBody');
      case 'completed':
        return createExecutionTranslationDescriptor('chat.trace.execution.completedBody');
      case 'failed':
        return createExecutionTranslationDescriptor('chat.trace.execution.failedBody');
      default:
        return createExecutionTranslationDescriptor('chat.trace.execution.runningBody');
    }
  })();
  const statusTitle = executionActionState.executionControl?.label
    || (executionState === 'running' ? String(traceSummary?.headline || message.content || '').trim() : '')
    || null;
  const normalizedPlanSummary: ProjectedExecutionProgressPresentation['planSummary'] = planSummary
    ? {
      parallelMode: planSummary.parallelMode === 'parallel' ? 'parallel' : 'sequential',
      totalSteps: planSummary.totalSteps,
      remainingSteps: planSummary.remainingSteps,
      steps: planSummary.steps.map((step, index) => ({
        key: String(step.subtaskId || step.label || `step-${index}`),
        label: step.label,
        status: normalizeExecutionPlanStepStatus(step.status),
      })),
    }
    : null;
  const runningStepIndex = normalizedPlanSummary?.steps.findIndex((step) => step.status === 'running') ?? -1;
  const resolvedRunningStep = runningStepIndex >= 0 ? runningStepIndex + 1 : 0;
  const totalStepsForStage = normalizedPlanSummary
    ? Math.max(normalizedPlanSummary.totalSteps, normalizedPlanSummary.steps.length, completedSteps)
    : 0;
  const planStage: ProjectedExecutionProgressPresentation['planStage'] = normalizedPlanSummary
    ? (() => {
      if (!totalStepsForStage) {
        return null;
      }
      switch (executionState) {
        case 'cancelling':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.cancelling', {
            completed: completedSteps,
            total: totalStepsForStage,
          });
        case 'cancelled':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.cancelled', {
            completed: completedSteps,
            total: totalStepsForStage,
          });
        case 'completed':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.completed', {
            completed: Math.max(completedSteps, totalStepsForStage),
            total: totalStepsForStage,
          });
        case 'failed':
          return resolvedRunningStep > 0
            ? createExecutionTranslationDescriptor('chat.trace.plan.stage.failedStep', {
              current: resolvedRunningStep,
              total: totalStepsForStage,
            })
            : createExecutionTranslationDescriptor('chat.trace.plan.stage.failedFallback', {
              completed: completedSteps,
              failed: failedSteps,
            });
        default:
          if (normalizedPlanSummary.parallelMode === 'parallel' && activeSteps > 1) {
            return createExecutionTranslationDescriptor('chat.trace.plan.stage.runningParallel', {
              active: activeSteps,
              completed: completedSteps,
              total: totalStepsForStage,
            });
          }
          if (resolvedRunningStep > 0) {
            return createExecutionTranslationDescriptor('chat.trace.plan.stage.runningStep', {
              current: resolvedRunningStep,
              total: totalStepsForStage,
            });
          }
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.runningFallback', {
            completed: completedSteps,
            total: totalStepsForStage,
          });
      }
    })()
    : null;
  const footer: ProjectedExecutionProgressPresentation['footer'] = (() => {
    switch (executionState) {
      case 'cancelled':
        return createExecutionTranslationDescriptor('chat.trace.execution.footerCancelled');
      case 'completed':
        return createExecutionTranslationDescriptor('chat.trace.execution.footerCompleted');
      case 'failed':
        return createExecutionTranslationDescriptor('chat.trace.execution.footerFailed');
      default:
        return null;
    }
  })();
  const contentText = String(message.content || '').trim();

  return {
    turnId,
    executionControlLabel: executionActionState.executionControl?.label || null,
    executionState,
    isCancelling: executionActionState.isCancelling,
    isDetaching: executionActionState.isDetaching,
    showCancelButton: executionActionState.showCancelButton,
    showDetachButton: executionActionState.showDetachButton,
    traceEntry,
    showSubtitle: turnId !== 'bootstrap-init-pending',
    statusTitle,
    statusTitleKey,
    subtitle,
    footer,
    planStage,
    showBubbleTitle: variant === 'card' || statusTitle !== contentText,
    indicator: executionState === 'cancelled' ? 'cancelled' : 'loader',
    showSpinningIndicator: executionState === 'running' || executionState === 'cancelling' || executionState === 'detaching',
    traceStats: traceSummary
      ? {
        activeSteps,
        completedSteps,
        failedSteps,
      }
      : null,
    planSummary: normalizedPlanSummary,
  };
};