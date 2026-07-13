import type { ChatTimelineMessage, ChatTimelineReplyPreview } from './state';

export type ChatPresentationSurface = 'transcript' | 'runtime_status' | 'control_status';

export interface ProjectedTranscriptBubbleTopPresentation {
  replyTo: ChatTimelineMessage['replyTo'] | null;
  attachments: ChatTimelineMessage['attachments'];
  showReplyStrip: boolean;
  showAttachments: boolean;
}

export interface ProjectedTranscriptBelowBubblePresentation {
  reactionText: string | null;
  showReactionBadge: boolean;
  label: ChatTimelineMessage['label'] | null;
  showMessageLabel: boolean;
  showUserTraceStatus: boolean;
}

export interface ProjectedTranscriptActionPresentation {
  replyPreview: ChatTimelineReplyPreview | null;
  canQuickLabel: boolean;
}

export interface ProjectedTraceEntryPresentation {
  turnId: string | null;
  canOpen: boolean;
  variant: 'default';
}

export interface ProjectedTranscriptPresentation {
  showHeaderTraceEntry: boolean;
  showExecutionBubbleFooter: boolean;
  showRecalledMemories: boolean;
  bubbleTop: ProjectedTranscriptBubbleTopPresentation;
  belowBubble: ProjectedTranscriptBelowBubblePresentation;
  actions: ProjectedTranscriptActionPresentation;
  traceEntry: ProjectedTraceEntryPresentation;
  executionProgress: ProjectedExecutionProgressPresentation | null;
}

export interface TurnExecutionControlState {
  state: string;
  label: string | null;
}

export interface ProjectedExecutionActionState {
  turnId: string;
  executionControl?: TurnExecutionControlState;
  executionState: string;
  isCancelling: boolean;
  isDetaching: boolean;
  showCancelButton: boolean;
  showDetachButton: boolean;
}

export interface ProjectedExecutionTranslationDescriptor {
  key: string;
  values?: Record<string, string | number>;
}

export interface ProjectedExecutionProgressPresentation {
  turnId: string | null;
  executionControlLabel: string | null;
  executionState: string;
  isCancelling: boolean;
  isDetaching: boolean;
  showCancelButton: boolean;
  showDetachButton: boolean;
  traceEntry: ProjectedTraceEntryPresentation;
  showSubtitle: boolean;
  statusTitle: string | null;
  statusTitleKey: string;
  subtitle: ProjectedExecutionTranslationDescriptor;
  footer: ProjectedExecutionTranslationDescriptor | null;
  planStage: ProjectedExecutionTranslationDescriptor | null;
  showBubbleTitle: boolean;
  indicator: 'cancelled' | 'loader';
  showSpinningIndicator: boolean;
  traceStats: {
    activeSteps: number;
    completedSteps: number;
    failedSteps: number;
  } | null;
  planSummary: {
    parallelMode: 'parallel' | 'sequential';
    totalSteps: number;
    remainingSteps: number;
    steps: Array<{
      key: string;
      label: string;
      status: 'pending' | 'running' | 'completed' | 'failed';
    }>;
  } | null;
}

export type ControlStatusTone = 'neutral' | 'warning' | 'danger' | 'success';

export interface ProjectedControlTodoItem {
  id: string;
  content: string;
  status: 'not_started' | 'in_progress' | 'completed';
}

export type ProjectedControlStatusCardPresentation =
  | {
    kind: 'background_task_completion';
    taskId: string | null;
    status: string;
    statusTone: ControlStatusTone;
    title: string | null;
    bodyText: string | null;
  }
  | {
    kind: 'background_task_pending';
    taskId: string | null;
    title: string | null;
    invocationText: string | null;
    skillName: string | null;
  }
  | {
    kind: 'permission_request';
    requestId: string | null;
    sessionId: string | null;
    tool: string;
    riskLevel: string;
    riskTone: ControlStatusTone;
    origin: string | null;
    argsPreview: string | null;
    expiresAtMs: number | null;
  }
  | {
    kind: 'ask_request';
    requestId: string | null;
    sessionId: string | null;
    question: string;
    options: string[];
    allowFreeText: boolean;
    isBackground: boolean;
    expiresAtMs: number | null;
  }
  | {
    kind: 'plan_state';
    active: boolean;
    planText: string | null;
  }
  | {
    kind: 'todo_state';
    items: ProjectedControlTodoItem[];
  };

export type ProjectedChatTimelineMessage = {
  message: ChatTimelineMessage;
  surface: 'control_status';
} | {
  message: ChatTimelineMessage;
  surface: 'runtime_status';
  executionProgress: ProjectedExecutionProgressPresentation | null;
} | {
  message: ChatTimelineMessage;
  surface: 'transcript';
  transcript: ProjectedTranscriptPresentation;
};
