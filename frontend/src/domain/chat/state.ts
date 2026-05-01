import type {
  ChatAttachment,
  ChatHistoryMessage,
  ChatMessageLabel,
  ChatReplyPreview,
  ExecutionTraceNode,
  ExecutionTraceSnapshot,
  ExecutionTraceSummary,
} from '@/api';
import { normalizeChatTimestamp } from '@/domain/chat/timestamps';

export const createClientTurnId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `turn_${crypto.randomUUID()}`;
  }
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
};

export type ChatMessageKind = 'user' | 'assistant' | 'status';

export interface ChatTimelineMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: ChatMessageKind;
  content: string;
  timestamp: number;
  messageId?: string;
  messageKind?: string | null;
  turnId?: string;
  reaction?: string | null;
  replyTo?: ChatTimelineReplyPreview | null;
  label?: ChatTimelineMessageLabel | null;
  attachments?: ChatAttachment[];
  traceDisplayMode?: string | null;
  allowTraceCollapse?: boolean;
  traceSummary?: NormalizedExecutionTraceSummary | null;
  traceAvailable?: boolean;
  streaming?: boolean;
  reasoning?: ReasoningTrace[];
  toolCalls?: ToolCallTrace[];
  payload?: Record<string, unknown> | null;
}

export interface ReasoningTrace {
  source: string;
  stepLabel?: string | null;
  content: string;
}

export interface ToolCallTrace {
  toolCallId?: string | null;
  toolName: string;
  status: 'running' | 'completed';
  toolArgsText?: string;
  toolArguments?: Record<string, unknown> | null;
}

export interface ChatTimelineReplyPreview {
  messageId: string;
  role: 'user' | 'assistant';
  messageKind?: string | null;
  contentExcerpt: string;
}

export interface ChatTimelineMessageLabel {
  kind: string;
  text: string;
  appliedBy: string;
  source: string;
  createdAtMs: number;
}

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
  orchestrationId?: string | null;
  planSummary?: NormalizedExecutionPlanSummary | null;
  continuedFromTurnId?: string | null;
  continuedFromTraceId?: string | null;
  supersededByTurnId?: string | null;
  supersessionReason?: string | null;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalReasoningTokens: number;
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
  orchestrationId?: string | null;
  startedAt?: number | null;
  endedAt?: number | null;
  continuedFromTurnId?: string | null;
  continuedFromTraceId?: string | null;
  supersededByTurnId?: string | null;
  supersessionReason?: string | null;
  summary: NormalizedExecutionTraceSummary;
  root: NormalizedExecutionTraceNode;
}

export interface NormalizedTurnUxPlan {
  assistantSurfaceMode: string;
  thinkingIndicator?: string | null;
  traceDisplayMode?: string | null;
  allowTraceCollapse?: boolean;
  interimText?: string | null;
  reactionStyle?: string | null;
}

type ApplyTurnUxPlanOptions = {
  pendingLabel?: string;
  messageId?: string;
  messageKind?: string | null;
  timestamp?: number;
};

const REACTION_EMOJI_BY_STYLE: Record<string, string> = {
  acknowledge: '👌',
};

const applyUxMetadata = (
  message: ChatTimelineMessage,
  plan: NormalizedTurnUxPlan,
): ChatTimelineMessage => ({
  ...message,
  traceDisplayMode: plan.traceDisplayMode ?? message.traceDisplayMode ?? null,
  allowTraceCollapse: typeof plan.allowTraceCollapse === 'boolean'
    ? plan.allowTraceCollapse
    : Boolean(message.allowTraceCollapse),
});

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
    orchestrationId: summary.orchestration_id || null,
    planSummary: normalizedPlanSummary,
    continuedFromTurnId: summary.continued_from_turn_id || null,
    continuedFromTraceId: summary.continued_from_trace_id || null,
    supersededByTurnId: summary.superseded_by_turn_id || null,
    supersessionReason: summary.supersession_reason || null,
    totalInputTokens: Number(summary.total_input_tokens || 0),
    totalOutputTokens: Number(summary.total_output_tokens || 0),
    totalReasoningTokens: Number(summary.total_reasoning_tokens || 0),
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
    orchestrationId: raw.orchestration_id || null,
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

export const normalizeTurnUxPlan = (raw: unknown): NormalizedTurnUxPlan | null => {
  if (!raw || typeof raw !== 'object') return null;
  const plan = raw as Record<string, unknown>;
  const assistantSurfaceMode = String(
    plan.assistantSurfaceMode || plan.assistant_surface_mode || ''
  ).trim();
  if (!assistantSurfaceMode) return null;

  const interimTextRaw = plan.interimText ?? plan.interim_text;
  const thinkingIndicatorRaw = plan.thinkingIndicator ?? plan.thinking_indicator;
  const traceDisplayModeRaw = plan.traceDisplayMode ?? plan.trace_display_mode;
  const reactionStyleRaw = plan.reactionStyle ?? plan.reaction_style;
  const allowTraceCollapseRaw = plan.allowTraceCollapse ?? plan.allow_trace_collapse;

  return {
    assistantSurfaceMode,
    thinkingIndicator: thinkingIndicatorRaw == null ? null : String(thinkingIndicatorRaw),
    traceDisplayMode: traceDisplayModeRaw == null ? null : String(traceDisplayModeRaw),
    allowTraceCollapse: Boolean(allowTraceCollapseRaw),
    interimText: interimTextRaw == null ? null : String(interimTextRaw),
    reactionStyle: reactionStyleRaw == null ? null : String(reactionStyleRaw),
  };
};

export const normalizeHistoryMessages = (messages: ChatHistoryMessage[]): ChatTimelineMessage[] => {
  const normalizedMessages: ChatTimelineMessage[] = [];

  messages.forEach((message, index) => {
    const rawMessageKind = String(message.message_kind || '').trim();
    const kind = (message.kind || message.role) as ChatMessageKind;
    const traceSummary = normalizeTraceSummary(message.trace_summary as ExecutionTraceSummary | undefined);
    const normalizedMessage: ChatTimelineMessage = {
      id: String(message.message_id || `${message.turn_id || 'history'}-${index}-${kind}`),
      role: message.role === 'user' ? 'user' : 'assistant',
      kind,
      content: message.content,
      timestamp: normalizeChatTimestamp(message.timestamp),
      messageId: message.message_id || undefined,
      messageKind: message.message_kind || null,
      turnId: message.turn_id || undefined,
      traceDisplayMode: message.trace_display_mode || null,
      allowTraceCollapse: Boolean(message.allow_trace_collapse),
      attachments: Array.isArray(message.attachments) ? message.attachments : undefined,
      replyTo: normalizeReplyPreview(message.reply_to),
      label: normalizeMessageLabel(message.label),
      traceSummary,
      traceAvailable: Boolean(message.trace_available || traceSummary?.traceAvailable),
      payload:
        message.payload && typeof message.payload === 'object'
          ? (message.payload as Record<string, unknown>)
          : null,
    };

    if (rawMessageKind === 'assistant_reaction') {
      const turnId = String(normalizedMessage.turnId || '').trim();
      const targetIndex = [...normalizedMessages]
        .map((item, itemIndex) => ({ item, itemIndex }))
        .reverse()
        .find(({ item }) => item.role === 'user' && String(item.turnId || '').trim() === turnId)
        ?.itemIndex;
      if (targetIndex !== undefined) {
        normalizedMessages[targetIndex] = {
          ...normalizedMessages[targetIndex],
          reaction: normalizedMessage.content,
        };
        return;
      }
    }

    normalizedMessages.push(normalizedMessage);
  });

  return normalizedMessages;
};

export const createPendingTurn = (
  input: string,
  turnId: string,
  timestamp: number,
  _pendingLabel: string,
  attachments: ChatAttachment[] = [],
  replyTo: ChatTimelineReplyPreview | null = null,
): ChatTimelineMessage[] => [
  {
    id: `${turnId}-user`,
    role: 'user',
    kind: 'user',
    content: input,
    timestamp,
    turnId,
    replyTo,
    attachments: attachments.length > 0 ? attachments : undefined,
    traceDisplayMode: null,
    allowTraceCollapse: false,
  },
];

export const applyTurnUxPlan = (
  messages: ChatTimelineMessage[],
  turnId: string,
  plan: NormalizedTurnUxPlan | null,
  options: ApplyTurnUxPlanOptions = {},
): ChatTimelineMessage[] => {
  const resolvedTurnId = String(turnId || '').trim();
  if (!resolvedTurnId || !plan) return messages;

  const buildSyntheticInterimMessage = (content: string): ChatTimelineMessage => ({
    id: String(options.messageId || `${resolvedTurnId}-assistant`),
    role: 'assistant',
    kind: 'assistant',
    content,
    timestamp: normalizeChatTimestamp(options.timestamp),
    messageId: options.messageId,
    messageKind: options.messageKind || 'assistant_interim',
    turnId: resolvedTurnId,
    traceAvailable: false,
  });

  if (plan.assistantSurfaceMode === 'reaction_only') {
    const reaction = REACTION_EMOJI_BY_STYLE[String(plan.reactionStyle || '').trim()] || '👌';
    const nextMessages = messages
      .filter((message) => !(message.turnId === resolvedTurnId && message.role === 'assistant'))
      .map((message) => (
        message.turnId === resolvedTurnId && message.role === 'user'
          ? applyUxMetadata({ ...message, reaction }, plan)
          : message
      ));
    return nextMessages;
  }

  if (plan.assistantSurfaceMode === 'interim_then_final') {
    const interimText = String(plan.interimText || '').trim();
    if (!interimText) return messages;

    const interimMessage = buildSyntheticInterimMessage(interimText);

    let replaced = false;
    const nextMessages = messages.map((message) => {
      if (message.turnId !== resolvedTurnId) return message;
      if (message.messageKind === 'assistant_interim' || message.kind === 'status') {
        replaced = true;
        return applyUxMetadata({
          ...message,
          ...interimMessage,
          traceSummary: message.traceSummary ?? null,
          traceAvailable: Boolean(message.traceAvailable),
        }, plan);
      }
      return message;
    });

    if (replaced) return nextMessages;
    return [...messages, applyUxMetadata(interimMessage, plan)];
  }

  if (plan.thinkingIndicator && plan.thinkingIndicator !== 'hidden') {
    const hasTurnFeedback = messages.some(
      (message) =>
        message.turnId === resolvedTurnId &&
        (message.kind === 'assistant' || message.kind === 'status')
    );
    if (hasTurnFeedback) {
      return messages;
    }
    return [
      ...messages,
      applyUxMetadata(
        buildSyntheticInterimMessage(String(options.pendingLabel || 'Thinking...')),
        plan,
      ),
    ];
  }

  return messages.map((message) => (
    message.turnId === resolvedTurnId ? applyUxMetadata(message, plan) : message
  ));
};

export const upsertTraceSummary = (
  messages: ChatTimelineMessage[],
  turnId: string,
  summary: NormalizedExecutionTraceSummary | null,
): ChatTimelineMessage[] => {
  if (!turnId) return messages;
  const nextSummary = summary || undefined;
  const anchorMessage = messages.find((message) => message.turnId === turnId);
  const traceDisplayMode = anchorMessage?.traceDisplayMode || null;
  let updated = false;
  const nextMessages = messages.map((message) => {
    if (message.turnId !== turnId) return message;
    if (message.kind === 'assistant') {
      updated = true;
      return {
        ...message,
        traceSummary: nextSummary || null,
        traceAvailable: Boolean(nextSummary?.traceAvailable),
      };
    }
    if (message.kind === 'status' && !String(message.messageKind || '').trim()) {
      updated = true;
      return {
        ...message,
        content: nextSummary?.headline || message.content,
        traceSummary: nextSummary || null,
        traceAvailable: Boolean(nextSummary?.traceAvailable),
      };
    }
    return message;
  });

  if (updated) return nextMessages;
  if (traceDisplayMode === 'none') return messages;
  if (
    nextSummary &&
    ['interrupted', 'merged'].includes(String(nextSummary.status || '').trim())
  ) {
    return messages.map((message) => (
      message.turnId === turnId && message.role === 'user'
        ? {
          ...message,
          traceSummary: nextSummary,
          traceAvailable: Boolean(nextSummary.traceAvailable),
        }
        : message
    ));
  }

  return [
    ...messages,
    {
      id: `${turnId}-assistant`,
      role: 'assistant',
      kind: 'assistant',
      content: nextSummary?.headline || 'Thinking...',
      timestamp: Date.now(),
      messageKind: 'assistant_interim',
      turnId,
      traceDisplayMode,
      allowTraceCollapse: Boolean(anchorMessage?.allowTraceCollapse),
      traceSummary: nextSummary || null,
      traceAvailable: Boolean(nextSummary?.traceAvailable),
    },
  ];
};

export const shouldShowTraceEntry = (
  message: Pick<ChatTimelineMessage, 'turnId' | 'traceDisplayMode' | 'traceAvailable' | 'traceSummary'>,
  summary?: { trace_available?: boolean } | null,
): boolean => {
  const turnId = String(message.turnId || '').trim();
  if (!turnId) return false;
  const traceDisplayMode = String(message.traceDisplayMode || '').trim() || 'collapsible';
  if (traceDisplayMode === 'none') return false;
  return Boolean(
    message.traceAvailable ||
    message.traceSummary?.traceAvailable ||
    summary?.trace_available
  );
};

export const applyAgentResponse = (
  messages: ChatTimelineMessage[],
  payload: {
    content: string;
    attachments?: ChatAttachment[];
    timestamp?: number;
    messageId?: string;
    messageKind?: string | null;
    turnId?: string;
    traceSummary?: NormalizedExecutionTraceSummary | null;
    traceAvailable?: boolean;
    uxPlan?: NormalizedTurnUxPlan | null;
    payload?: Record<string, unknown> | null;
  },
): ChatTimelineMessage[] => {
  const isTransientStatusMessage = (message: ChatTimelineMessage): boolean => (
    message.kind === 'status' && !String(message.messageKind || '').trim()
  );

  const turnId = String(payload.turnId || '').trim();
  const timestamp = normalizeChatTimestamp(payload.timestamp);
  const traceSummary = payload.traceSummary || null;
  const traceAvailable = Boolean(payload.traceAvailable || traceSummary?.traceAvailable);
  const uxPlan = payload.uxPlan || null;
  const messageKind = String(payload.messageKind || '').trim();

  if (messageKind === 'assistant_reaction' && turnId) {
    return messages
      .filter((message) => !(message.turnId === turnId && message.kind === 'assistant'))
      .map((message) => {
        if (message.turnId !== turnId || message.role !== 'user') {
          return message;
        }
        return applyUxMetadata(
          {
            ...message,
            reaction: payload.content,
            traceSummary,
            traceAvailable,
          },
          uxPlan ?? {
            assistantSurfaceMode: 'reaction_only',
          }
        );
      });
  }

  const buildAssistantMessage = (resolvedTurnId?: string): ChatTimelineMessage => ({
    id: String(payload.messageId || `${resolvedTurnId || turnId || 'assistant'}-assistant-${timestamp}`),
    role: 'assistant',
    kind: 'assistant',
    content: payload.content,
    attachments: Array.isArray(payload.attachments) && payload.attachments.length > 0 ? payload.attachments : undefined,
    timestamp,
    messageId: payload.messageId,
    messageKind: payload.messageKind || 'assistant_final',
    turnId: resolvedTurnId || turnId || undefined,
    traceDisplayMode: uxPlan?.traceDisplayMode ?? null,
    allowTraceCollapse: Boolean(uxPlan?.allowTraceCollapse),
    traceSummary,
    traceAvailable,
    payload: payload.payload ?? null,
  });

  const hasInterimAssistant = turnId
    ? messages.some(
      (message) =>
        message.turnId === turnId
        && message.kind === 'assistant'
        && message.messageKind === 'assistant_interim'
    )
    : false;
  const hasRhythmSegments = turnId
    ? messages.some(
      (message) =>
        message.turnId === turnId
        && message.kind === 'assistant'
        && message.messageKind === 'assistant_rhythm_segment'
    )
    : false;

  if (messageKind === 'assistant_rhythm_segment' && turnId) {
    const incoming = buildAssistantMessage(turnId);
    const withoutTransientStatus = messages.filter(
      (message) => !(message.turnId === turnId && isTransientStatusMessage(message)),
    );
    const existingIndex = withoutTransientStatus.findIndex(
      (message) => Boolean(payload.messageId) && message.messageId === payload.messageId,
    );
    if (existingIndex >= 0) {
      return withoutTransientStatus.map((message, index) => (index === existingIndex ? incoming : message));
    }
    return [...withoutTransientStatus, incoming];
  }

  if (hasRhythmSegments && !String(payload.messageId || '').trim()) {
    return messages.map((message) => {
      if (message.turnId !== turnId || message.messageKind !== 'assistant_rhythm_segment') {
        return message;
      }
      return {
        ...message,
        traceSummary: traceSummary ?? message.traceSummary ?? null,
        traceAvailable: traceAvailable || Boolean(message.traceAvailable),
      };
    });
  }

  if (!turnId) {
    const lastStatusIndex = [...messages]
      .map((message, index) => ({ message, index }))
      .reverse()
      .find(({ message }) => isTransientStatusMessage(message))
      ?.index;
    if (lastStatusIndex !== undefined) {
      const fallbackTurnId = messages[lastStatusIndex]?.turnId;
      return messages.map((message, index) =>
        index === lastStatusIndex ? buildAssistantMessage(fallbackTurnId) : message
      );
    }
    const fallbackTurnId = [...messages]
      .map((message) => String(message.turnId || '').trim())
      .reverse()
      .find(Boolean);
    if (fallbackTurnId) {
      return [...messages, { ...buildAssistantMessage(fallbackTurnId), id: String(payload.messageId || `${fallbackTurnId}-assistant`), turnId: fallbackTurnId }];
    }
    return [...messages, buildAssistantMessage()];
  }

  let replaced = false;
  if (hasInterimAssistant) {
    const existingFinalIndex = messages.findIndex(
      (message) =>
        message.turnId === turnId
        && message.kind === 'assistant'
        && message.messageKind !== 'assistant_interim'
    );
    if (existingFinalIndex >= 0) {
      return messages.map((message, index) =>
        index === existingFinalIndex ? buildAssistantMessage(turnId) : message
      );
    }
    return [...messages, buildAssistantMessage(turnId)];
  }

  const nextMessages = messages.map((message) => {
    if (message.turnId !== turnId) return message;
    if (message.kind === 'assistant' || isTransientStatusMessage(message)) {
      replaced = true;
      return { ...buildAssistantMessage(turnId), turnId };
    }
    return message;
  });

  if (replaced) return nextMessages;

  const fallbackStatusIndex = [...messages]
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => isTransientStatusMessage(message))
    ?.index;

  if (fallbackStatusIndex !== undefined) {
    return messages.map((message, index) =>
      index === fallbackStatusIndex ? { ...buildAssistantMessage(turnId), turnId } : message
    );
  }

  return [...messages, { ...buildAssistantMessage(turnId), turnId }];
};

const normalizeReplyPreview = (
  preview: ChatReplyPreview | null | undefined,
): ChatTimelineReplyPreview | null => {
  if (!preview || typeof preview !== 'object') {
    return null;
  }
  const messageId = String(preview.message_id || '').trim();
  if (!messageId) {
    return null;
  }
  return {
    messageId,
    role: preview.role === 'user' ? 'user' : 'assistant',
    messageKind: preview.message_kind || null,
    contentExcerpt: String(preview.content_excerpt || '').trim(),
  };
};

export const normalizeMessageLabel = (
  label: ChatMessageLabel | null | undefined,
): ChatTimelineMessageLabel | null => {
  if (!label || typeof label !== 'object') {
    return null;
  }
  const kind = String(label.kind || '').trim();
  const text = String(label.text || '').trim();
  const appliedBy = String(label.applied_by || '').trim();
  const source = String(label.source || '').trim();
  const createdAtMs = Number(label.created_at_ms || 0);
  if (!kind || !text || !appliedBy || !source || createdAtMs <= 0) {
    return null;
  }
  return {
    kind,
    text,
    appliedBy,
    source,
    createdAtMs,
  };
};
