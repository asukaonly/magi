import type { ChatTimelineMessage } from './state';
import { shouldShowTraceEntry } from './state';
import type {
  ProjectedExecutionActionState,
  ProjectedExecutionProgressPresentation,
  ProjectedExecutionTranslationDescriptor,
  ProjectedTraceEntryPresentation,
  TurnExecutionControlState,
} from './presentation.types';
import {
  isTerminalRunState,
  normalizeRunState,
  normalizeTerminalRunState,
} from './run-state';

type ExecutionActionProjectionInput = {
  executionControlByTurnId: Record<string, TurnExecutionControlState>;
  cancellingTurnIds: string[];
  detachingTurnIds: string[];
};

export type ChatTimelineExecutionProjectionInput = ExecutionActionProjectionInput & {
  summaries: Record<string, { traceAvailable?: boolean }>;
  finalizedTurnIds?: ReadonlySet<string>;
};

type ProjectedExecutionTranslationValues = Record<string, string | number>;

const GENERIC_EXECUTION_LABELS = new Set([
  'thinking',
  'running tool chain',
  'tool chain completed',
  'tool chain failed',
  'orchestrating tasks',
  'moving run to background',
  'cancelling run',
  'run cancelled',
  'run completed',
  'run failed',
  'run blocked',
  '思考中',
  '正在执行工具链',
  '工具链已完成',
  '工具链执行失败',
  '正在编排任务',
  '正在转到后台',
]);

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
    case 'blocked':
      return 'failed';
    case 'skipped':
    case 'cancelled':
      return 'completed';
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

const normalizeExecutionDisplayLabel = (
  value: string | null | undefined,
): string | null => {
  const trimmed = String(value || '').trim();
  if (!trimmed) {
    return null;
  }

  return GENERIC_EXECUTION_LABELS.has(trimmed.toLowerCase()) ? null : trimmed;
};

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
  const traceStatus = normalizeRunState(message.traceSummary?.status) || 'running';
  const backendRunState = normalizeRunState(message.runState?.state);
  const executionControlState = normalizeRunState(executionControl?.state);
  const terminalBackendRunState = normalizeTerminalRunState(backendRunState) || '';
  const optimisticState = turnId && detachingTurnIds.includes(turnId)
    ? 'detaching'
    : turnId && cancellingTurnIds.includes(turnId)
      ? 'cancelling'
      : '';
  const executionState = terminalBackendRunState
    || optimisticState
    || executionControlState
    || backendRunState
    || traceStatus;
  const isTerminal = isTerminalRunState(executionState);
  const isCancelling = executionState === 'cancelling';
  const isDetaching = executionState === 'detaching';
  const canCancel = typeof message.runState?.can_cancel === 'boolean'
    ? message.runState.can_cancel
    : executionState === 'running' || executionState === 'cancelling';
  const canDetach = typeof message.runState?.can_detach === 'boolean'
    ? message.runState.can_detach
    : executionState === 'running';

  return {
    turnId,
    executionControl,
    executionState,
    isCancelling,
    isDetaching,
    showCancelButton: Boolean(turnId) && !isTerminal && canCancel,
    showDetachButton: Boolean(turnId) && !isTerminal && canDetach,
  };
};

export const projectTraceEntryPresentation = (
  message: Pick<ChatTimelineMessage, 'turnId' | 'traceDisplayMode' | 'traceAvailable' | 'traceSummary'>,
  summary?: { traceAvailable?: boolean } | null,
): ProjectedTraceEntryPresentation => {
  const turnId = String(message.turnId || '').trim();

  return {
    turnId: turnId || null,
    canOpen: shouldShowTraceEntry(message, summary),
    variant: 'default',
  };
};

export const projectExecutionProgressPresentation = (
  message: ChatTimelineMessage,
  options: ExecutionActionProjectionInput & {
    summary?: { traceAvailable?: boolean } | null;
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
  const terminalState = normalizeTerminalRunState(executionState);
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
      case 'blocked':
        return 'chat.trace.execution.blockedTitle';
      case 'interrupted':
        return 'chat.trace.execution.interruptedTitle';
      case 'merged':
        return 'chat.trace.execution.mergedTitle';
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
      case 'blocked':
        return createExecutionTranslationDescriptor('chat.trace.execution.blockedBody');
      case 'interrupted':
        return createExecutionTranslationDescriptor('chat.trace.execution.interruptedBody');
      case 'merged':
        return createExecutionTranslationDescriptor('chat.trace.execution.mergedBody');
      default:
        return createExecutionTranslationDescriptor('chat.trace.execution.runningBody');
    }
  })();
  const statusTitle = terminalState
    ? null
    : normalizeExecutionDisplayLabel(executionActionState.executionControl?.label)
      || (executionState === 'running'
        ? normalizeExecutionDisplayLabel(traceSummary?.headline || message.content || '')
        : null)
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
    ? Math.max(normalizedPlanSummary.totalSteps, normalizedPlanSummary.steps.length)
    : 0;
  const completedPlanSteps = normalizedPlanSummary
    ? Math.min(
      totalStepsForStage,
      Math.max(0, totalStepsForStage - normalizedPlanSummary.remainingSteps),
    )
    : 0;
  const planStage: ProjectedExecutionProgressPresentation['planStage'] = normalizedPlanSummary
    ? (() => {
      if (!totalStepsForStage) {
        return null;
      }
      switch (executionState) {
        case 'cancelling':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.cancelling', {
            completed: completedPlanSteps,
            total: totalStepsForStage,
          });
        case 'cancelled':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.cancelled', {
            completed: completedPlanSteps,
            total: totalStepsForStage,
          });
        case 'completed':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.completed', {
            completed: totalStepsForStage,
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
        case 'blocked':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.blocked', {
            completed: completedPlanSteps,
            total: totalStepsForStage,
          });
        case 'interrupted':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.interrupted', {
            completed: completedPlanSteps,
            total: totalStepsForStage,
          });
        case 'merged':
          return createExecutionTranslationDescriptor('chat.trace.plan.stage.merged', {
            completed: completedPlanSteps,
            total: totalStepsForStage,
          });
        default:
          if (normalizedPlanSummary.parallelMode === 'parallel' && activeSteps > 1) {
            return createExecutionTranslationDescriptor('chat.trace.plan.stage.runningParallel', {
              active: activeSteps,
              completed: completedPlanSteps,
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
            completed: completedPlanSteps,
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
      case 'blocked':
        return createExecutionTranslationDescriptor('chat.trace.execution.footerBlocked');
      case 'interrupted':
        return createExecutionTranslationDescriptor('chat.trace.execution.footerInterrupted');
      case 'merged':
        return createExecutionTranslationDescriptor('chat.trace.execution.footerMerged');
      default:
        return null;
    }
  })();
  const contentText = String(message.content || '').trim();
  const runningBubbleUsesMessageText = variant === 'bubble'
    && executionState === 'running'
    && contentText.length > 0;

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
    showBubbleTitle: variant === 'card' || (!runningBubbleUsesMessageText && statusTitle !== contentText),
    indicator: terminalState || 'progress',
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
