import type { RefObject } from 'react';
import type { TurnExecutionControlState } from '@/domain/chat/presentation';
import type { ChatTimelineMessage, ChatTimelineReplyPreview, NormalizedExecutionTraceSummary } from '@/domain/chat/state';
import type { LabelPopoverState } from '@/hooks/useChatMessageOverlays';
import type { RecallFeedbackDraftInput } from '@/domain/chat/recall-feedback';

export type TimelineAssistantPersona = {
  name: string;
  avatar: string;
};

export type TimelineAssistantIdentity = {
  name: string;
  avatar: string;
  personas?: Record<string, TimelineAssistantPersona>;
};

export type TimelineExecutionBindings = {
  summaries: Record<string, NormalizedExecutionTraceSummary>;
  executionControlByTurnId: Record<string, TurnExecutionControlState>;
  cancellingTurnIds: string[];
  detachingTurnIds: string[];
  onOpenTraceDrawer: (turnId: string) => void;
  onRequestRunCancel: (turnId: string) => void;
  onRequestRunDetach: (turnId: string) => void;
};

export type TimelineRowSharedProps = {
  assistant: TimelineAssistantIdentity;
  shouldReduceMotion: boolean;
  execution: TimelineExecutionBindings;
};

export type TranscriptTimelineInteractions = {
  currentSessionId: string | null;
  labelPopoverState: LabelPopoverState | null;
  labelPopoverDraft: string;
  labelPopoverRef: RefObject<HTMLDivElement>;
  onSetReplyTarget: (reply: ChatTimelineReplyPreview | null) => void;
  onOpenImagePreview: (payload: { name: string; url: string }) => void;
  onCloseLabelPopover: () => void;
  onCloseMessageContextMenu: () => void;
  onOpenLabelPopover: (messageId: string, position: { x: number; y: number }) => void;
  onOpenMessageContextMenu: (message: ChatTimelineMessage, position: { x: number; y: number }) => void;
  onApplyLabelToMessage: (message: ChatTimelineMessage, nextLabel: { kind: string; text: string }) => void;
  onLabelDraftChange: (value: string) => void;
  onLabelDraftCompositionStart: () => void;
  onLabelDraftCompositionEnd: (value: string) => void;
  recallFeedbackDisabled?: boolean;
  onStartRecallFeedback?: (draft: RecallFeedbackDraftInput) => void;
};
