import type {
  ExecutionTraceNode,
  ExecutionTraceSnapshot,
  ExecutionTraceSummary,
} from '@/api';

export interface NormalizedExecutionTraceSummary {
  turnId: string;
  mode: string;
  status: string;
  headline: string;
  activeSteps: number;
  completedSteps: number;
  failedSteps: number;
  durationSeconds: number;
  traceAvailable: boolean;
  planSummary?: NormalizedExecutionPlanSummary | null;
  continuedFromTurnId?: string | null;
  continuedFromTraceId?: string | null;
  supersededByTurnId?: string | null;
  supersessionReason?: string | null;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalReasoningTokens: number;
  runtimeMetrics: Record<string, number | null>;
}

export interface NormalizedExecutionPlanSummary {
  planner?: string | null;
  parallelMode: string;
  totalSteps: number;
  remainingSteps: number;
  steps: NormalizedExecutionPlanStep[];
}

export interface NormalizedExecutionPlanStep {
  subtaskId?: string | null;
  label: string;
  status: string;
}

export interface NormalizedExecutionTraceNode {
  id: string;
  kind: string;
  label: string;
  status: string;
  startedAt?: number | null;
  endedAt?: number | null;
  resultPreview?: string;
  error?: string | null;
  metadata: Record<string, unknown>;
  children: NormalizedExecutionTraceNode[];
}

export interface NormalizedExecutionTraceSnapshot {
  turnId: string;
  userId: string;
  sessionId: string;
  status: string;
  mode: string;
  startedAt?: number | null;
  endedAt?: number | null;
  continuedFromTurnId?: string | null;
  continuedFromTraceId?: string | null;
  supersededByTurnId?: string | null;
  supersessionReason?: string | null;
  summary: NormalizedExecutionTraceSummary;
  root: NormalizedExecutionTraceNode;
}

type TraceEntryMessage = {
  turnId?: string;
  traceDisplayMode?: string | null;
  traceAvailable?: boolean;
  traceSummary?: NormalizedExecutionTraceSummary | null;
};

export const normalizeTraceSummary = (raw: unknown): NormalizedExecutionTraceSummary | null => {
  if (!raw || typeof raw !== 'object') return null;
  const summary = raw as ExecutionTraceSummary;
  const turnId = String(summary.turn_id || '').trim();
  if (!turnId) return null;
  const rawPlanSummary = summary.plan_summary;
  const normalizedPlanSummary = rawPlanSummary && typeof rawPlanSummary === 'object'
    ? {
      planner: rawPlanSummary.planner || null,
      parallelMode: String(rawPlanSummary.parallel_mode || 'parallel'),
      totalSteps: Number(rawPlanSummary.total_steps || 0),
      remainingSteps: Number(rawPlanSummary.remaining_steps || 0),
      steps: Array.isArray(rawPlanSummary.steps)
        ? rawPlanSummary.steps
          .filter((step): step is NonNullable<typeof rawPlanSummary.steps>[number] => Boolean(step && typeof step === 'object'))
          .map((step) => ({
            subtaskId: step.subtask_id || null,
            label: String(step.label || ''),
            status: String(step.status || 'pending'),
          }))
          .filter((step) => step.label.length > 0)
        : [],
    }
    : null;
  return {
    turnId,
    mode: String(summary.mode || 'function_calling'),
    status: String(summary.status || 'running'),
    headline: String(summary.headline || ''),
    activeSteps: Number(summary.active_steps || 0),
    completedSteps: Number(summary.completed_steps || 0),
    failedSteps: Number(summary.failed_steps || 0),
    durationSeconds: Number(summary.duration_seconds || 0),
    traceAvailable: Boolean(summary.trace_available),
    planSummary: normalizedPlanSummary,
    continuedFromTurnId: summary.continued_from_turn_id || null,
    continuedFromTraceId: summary.continued_from_trace_id || null,
    supersededByTurnId: summary.superseded_by_turn_id || null,
    supersessionReason: summary.supersession_reason || null,
    totalInputTokens: Number(summary.total_input_tokens || 0),
    totalOutputTokens: Number(summary.total_output_tokens || 0),
    totalReasoningTokens: Number(summary.total_reasoning_tokens || 0),
    runtimeMetrics: Object.fromEntries(
      Object.entries(summary.runtime_metrics || {})
        .filter(([, value]) => value === null || typeof value === 'number'),
    ),
  };
};

export const normalizeTraceNode = (raw: ExecutionTraceNode): NormalizedExecutionTraceNode => ({
  id: raw.id,
  kind: raw.kind,
  label: raw.label,
  status: raw.status,
  startedAt: raw.started_at ?? null,
  endedAt: raw.ended_at ?? null,
  resultPreview: raw.result_preview || '',
  error: raw.error || null,
  metadata: (raw.metadata || {}) as Record<string, unknown>,
  children: Array.isArray(raw.children) ? raw.children.map(normalizeTraceNode) : [],
});

const isTerminalTraceStatus = (status: string | null | undefined): boolean => (
  status === 'completed' || status === 'failed' || status === 'interrupted' || status === 'merged'
);

const deriveTraceRollupStatus = (children: NormalizedExecutionTraceNode[]): string => {
  if (children.some((child) => child.status === 'failed')) {
    return 'failed';
  }
  if (children.some((child) => child.status === 'running')) {
    return 'running';
  }
  if (children.some((child) => child.status === 'pending')) {
    return 'pending';
  }
  if (children.some((child) => child.status === 'interrupted')) {
    return 'interrupted';
  }
  if (children.some((child) => child.status === 'merged')) {
    return 'merged';
  }
  return children.every((child) => child.status === 'completed') ? 'completed' : 'running';
};

const getDispatchDisplayLabel = (node: NormalizedExecutionTraceNode): string => {
  const metadata = node.metadata || {};
  const explicitLabel = typeof metadata.dispatch_label === 'string' ? metadata.dispatch_label.trim() : '';
  if (explicitLabel) {
    return explicitLabel;
  }
  const previewLabel = String(node.resultPreview || '').trim();
  if (previewLabel) {
    return previewLabel;
  }
  return node.label;
};

const relabelTraceNodeForDisplay = (
  node: NormalizedExecutionTraceNode,
): NormalizedExecutionTraceNode => {
  const children = node.children.map(relabelTraceNodeForDisplay);
  if (node.kind !== 'dispatch') {
    return {
      ...node,
      children,
    };
  }

  const displayLabel = getDispatchDisplayLabel(node).trim();
  const preview = String(node.resultPreview || '').trim();
  return {
    ...node,
    label: displayLabel || node.label,
    resultPreview: displayLabel && preview === displayLabel ? '' : node.resultPreview,
    metadata: {
      ...node.metadata,
      dispatch_label: displayLabel || node.label,
    },
    children,
  };
};

const reshapeTraceRootForDisplay = (
  root: NormalizedExecutionTraceNode,
): NormalizedExecutionTraceNode => {
  const relabeledRoot = relabelTraceNodeForDisplay(root);
  if (relabeledRoot.kind !== 'root' || relabeledRoot.children.length === 0) {
    return relabeledRoot;
  }

  const hasPlanningNode = relabeledRoot.children.some((child) => child.kind === 'planning');
  if (hasPlanningNode) {
    return relabeledRoot;
  }

  const planningChildren: NormalizedExecutionTraceNode[] = [];
  const preservedChildren: NormalizedExecutionTraceNode[] = [];
  let insertIndex: number | null = null;
  let hiddenIterationCount = 0;

  relabeledRoot.children.forEach((child) => {
    if (child.kind === 'dispatch') {
      if (insertIndex === null) {
        insertIndex = preservedChildren.length;
      }
      planningChildren.push(child);
      return;
    }
    if (child.kind === 'iteration') {
      if (insertIndex === null) {
        insertIndex = preservedChildren.length;
      }
      hiddenIterationCount += 1;
      return;
    }
    preservedChildren.push(child);
  });

  if (planningChildren.length === 0) {
    return relabeledRoot;
  }

  const startedAtCandidates = planningChildren
    .map((child) => child.startedAt)
    .filter((value): value is number => typeof value === 'number');
  const planningStatus = deriveTraceRollupStatus(planningChildren);
  const endedAtCandidates = planningChildren
    .map((child) => child.endedAt)
    .filter((value): value is number => typeof value === 'number');
  const planningNode: NormalizedExecutionTraceNode = {
    id: `${relabeledRoot.id}:planning`,
    kind: 'planning',
    label: 'Task orchestration',
    status: planningStatus,
    startedAt: startedAtCandidates.length > 0 ? Math.min(...startedAtCandidates) : relabeledRoot.startedAt,
    endedAt: endedAtCandidates.length > 0 && isTerminalTraceStatus(planningStatus)
      ? Math.max(...endedAtCandidates)
      : null,
    resultPreview: '',
    error: null,
    metadata: {
      synthetic: true,
      hidden_iteration_count: hiddenIterationCount,
    },
    children: planningChildren,
  };

  preservedChildren.splice(insertIndex ?? preservedChildren.length, 0, planningNode);
  return {
    ...relabeledRoot,
    children: preservedChildren,
  };
};

export const flattenPlanningNodeForDisplay = (
  root: NormalizedExecutionTraceNode,
): NormalizedExecutionTraceNode => {
  return reshapeTraceRootForDisplay(root);
};

export const normalizeTraceSnapshot = (raw: ExecutionTraceSnapshot | null | undefined): NormalizedExecutionTraceSnapshot | null => {
  if (!raw) return null;
  const summary = normalizeTraceSummary(raw.summary);
  if (!summary) return null;
  return {
    turnId: raw.turn_id,
    userId: raw.user_id,
    sessionId: raw.session_id,
    status: raw.status,
    mode: raw.mode,
    startedAt: raw.started_at ?? null,
    endedAt: raw.ended_at ?? null,
    continuedFromTurnId: raw.continued_from_turn_id || null,
    continuedFromTraceId: raw.continued_from_trace_id || null,
    supersededByTurnId: raw.superseded_by_turn_id || null,
    supersessionReason: raw.supersession_reason || null,
    summary,
    root: normalizeTraceNode(raw.root),
  };
};

export const shouldShowTraceEntry = (
  message: TraceEntryMessage,
  summary?: { traceAvailable?: boolean } | null,
): boolean => {
  const turnId = String(message.turnId || '').trim();
  if (!turnId) return false;
  const traceDisplayMode = String(message.traceDisplayMode || '').trim() || 'collapsible';
  if (traceDisplayMode === 'none') return false;
  return Boolean(
    message.traceAvailable ||
    message.traceSummary?.traceAvailable ||
    summary?.traceAvailable
  );
};
