import type { RefObject } from 'react';
import { useMemo } from 'react';
import { projectChatTimelineRow, type TurnExecutionControlState } from '@/domain/chat/presentation';
import { isPendingRunState } from '@/domain/chat/run-state';
import type { ChatTimelineMessage, ChatTimelineReplyPreview, NormalizedExecutionTraceSummary } from '@/domain/chat/state';
import type { LabelPopoverState, MessageContextMenuState } from '@/hooks/useChatMessageOverlays';
import type { RecallFeedbackDraftInput } from '@/domain/chat/recall-feedback';
import { ChatMessageContextMenuOverlay } from './ChatMessageContextMenuOverlay';
import { PendingAssistantBubble } from './PendingAssistantBubble';
import { StatusTimelineRow } from './StatusTimelineRow';
import type {
  TimelineAssistantIdentity,
  TimelineAssistantPersona,
  TimelineExecutionBindings,
  TranscriptTimelineInteractions,
} from './TimelineRowShared';
import { TranscriptTimelineRow } from './TranscriptTimelineRow';

type RenderableTimelineMessage = ReturnType<typeof projectChatTimelineRow>;

const executionPlaceholderPriority = (projectedMessage: RenderableTimelineMessage): number => {
  if (projectedMessage.surface === 'runtime_status') {
    return projectedMessage.executionProgress ? 1 : 0;
  }
  if (
    projectedMessage.surface === 'transcript'
    && projectedMessage.message.messageKind === 'assistant_interim'
    && projectedMessage.transcript.executionProgress
  ) {
    return 2;
  }
  return 0;
};

const shouldPinExecutionPlaceholderToTail = (projectedMessage: RenderableTimelineMessage): boolean => {
  const turnId = String(projectedMessage.message.turnId || '').trim();
  if (!turnId) {
    return false;
  }
  const executionProgress = projectedMessage.surface === 'runtime_status'
    ? projectedMessage.executionProgress
    : projectedMessage.surface === 'transcript'
      ? projectedMessage.transcript.executionProgress
      : null;
  return Boolean(
    executionProgress
    && isPendingRunState(executionProgress.executionState),
  );
};

type ChatTimelinePaneProps = {
  messages: ChatTimelineMessage[];
  assistantName: string;
  assistantAvatar: string;
  assistantPersonas: Record<string, TimelineAssistantPersona>;
  currentSessionId: string | null;
  shouldReduceMotion: boolean;
  summaries: Record<string, NormalizedExecutionTraceSummary>;
  executionControlByTurnId: Record<string, TurnExecutionControlState>;
  cancellingTurnIds: string[];
  detachingTurnIds: string[];
  labelPopoverState: LabelPopoverState | null;
  labelPopoverDraft: string;
  labelPopoverRef: RefObject<HTMLDivElement>;
  messageContextMenu: MessageContextMenuState | null;
  messageContextMenuRef: RefObject<HTMLDivElement>;
  messagesEndRef?: RefObject<HTMLDivElement>;
  timelineRef: RefObject<HTMLDivElement>;
  /**
   * True while a turn is in flight — set after the user sends and cleared when
   * the assistant turn completes. Used to decide whether to render the
   * PendingAssistantBubble (only shows when waiting AND no assistant row
   * has appeared yet for the latest turn — see ``showPendingBubble`` below).
   */
  waitingForReply: boolean;
  onSetReplyTarget: (reply: ChatTimelineReplyPreview | null) => void;
  onOpenImagePreview: (payload: { name: string; url: string }) => void;
  onOpenTraceDrawer: (turnId: string) => void;
  onRequestRunCancel: (turnId: string) => void;
  onRequestRunDetach: (turnId: string) => void;
  onCloseLabelPopover: () => void;
  onCloseMessageContextMenu: () => void;
  onOpenLabelPopover: (messageId: string, position: { x: number; y: number }) => void;
  onOpenMessageContextMenu: (message: ChatTimelineMessage, position: { x: number; y: number }) => void;
  onApplyLabelToMessage: (message: ChatTimelineMessage, nextLabel: { kind: string; text: string }) => void;
  onLabelDraftChange: (value: string) => void;
  onLabelDraftCompositionStart: () => void;
  onLabelDraftCompositionEnd: (value: string) => void;
  onCopyMessage: (message: ChatTimelineMessage, mode: 'markdown' | 'plain') => void;
  onDeleteMessage: (message: ChatTimelineMessage) => void;
  recallFeedbackDisabled: boolean;
  onStartRecallFeedback: (draft: RecallFeedbackDraftInput) => void;
};

export const ChatTimelinePane = ({
  messages,
  assistantName,
  assistantAvatar,
  assistantPersonas,
  currentSessionId,
  shouldReduceMotion,
  summaries,
  executionControlByTurnId,
  cancellingTurnIds,
  detachingTurnIds,
  labelPopoverState,
  labelPopoverDraft,
  labelPopoverRef,
  messageContextMenu,
  messageContextMenuRef,
  messagesEndRef,
  timelineRef,
  waitingForReply,
  onSetReplyTarget,
  onOpenImagePreview,
  onOpenTraceDrawer,
  onRequestRunCancel,
  onRequestRunDetach,
  onCloseLabelPopover,
  onCloseMessageContextMenu,
  onOpenLabelPopover,
  onOpenMessageContextMenu,
  onApplyLabelToMessage,
  onLabelDraftChange,
  onLabelDraftCompositionStart,
  onLabelDraftCompositionEnd,
  onCopyMessage,
  onDeleteMessage,
  recallFeedbackDisabled,
  onStartRecallFeedback,
}: ChatTimelinePaneProps) => {
  const assistant: TimelineAssistantIdentity = {
    name: assistantName,
    avatar: assistantAvatar,
    personas: assistantPersonas,
  };
  const execution: TimelineExecutionBindings = {
    summaries,
    executionControlByTurnId,
    cancellingTurnIds,
    detachingTurnIds,
    onOpenTraceDrawer,
    onRequestRunCancel,
    onRequestRunDetach,
  };
  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'assistant') {
        return messages[i].id;
      }
    }
    return null;
  }, [messages]);
  const finalizedTurnIds = useMemo(() => {
    const ids = new Set<string>();
    for (const message of messages) {
      if (message.role !== 'assistant' || message.kind !== 'assistant') {
        continue;
      }
      const turnId = String(message.turnId || '').trim();
      if (!turnId) {
        continue;
      }
      const messageKind = String(message.messageKind || '').trim();
      if (messageKind === 'assistant_interim') {
        continue;
      }
      ids.add(turnId);
    }
    return ids;
  }, [messages]);
  const correctedMessageIds = useMemo(() => {
    const ids = new Set<string>();
    for (const message of messages) {
      const targetMessageId = String(message.payload?.corrects_message_id || '').trim();
      if (targetMessageId) {
        ids.add(targetMessageId);
      }
    }
    return ids;
  }, [messages]);
  const projectedMessages = useMemo(() => {
    const projected = messages.map((message) => projectChatTimelineRow(message, {
      summaries,
      executionControlByTurnId,
      cancellingTurnIds,
      detachingTurnIds,
      finalizedTurnIds,
    }));
    const canonicalPlaceholderByTurnId = new Map<string, {
      index: number;
      priority: number;
    }>();

    projected.forEach((projectedMessage, index) => {
      const priority = executionPlaceholderPriority(projectedMessage);
      const turnId = String(projectedMessage.message.turnId || '').trim();
      if (!turnId || priority === 0) {
        return;
      }
      const current = canonicalPlaceholderByTurnId.get(turnId);
      if (!current || priority >= current.priority) {
        canonicalPlaceholderByTurnId.set(turnId, { index, priority });
      }
    });

    const regular: RenderableTimelineMessage[] = [];
    const tailPlaceholders: RenderableTimelineMessage[] = [];

    projected.forEach((projectedMessage, index) => {
      const projectedTurnId = String(projectedMessage.message.turnId || '').trim();
      if (projectedMessage.surface === 'runtime_status' && projectedTurnId && finalizedTurnIds.has(projectedTurnId)) {
        return;
      }
      const placeholderPriority = executionPlaceholderPriority(projectedMessage);
      if (
        projectedTurnId
        && placeholderPriority > 0
        && canonicalPlaceholderByTurnId.get(projectedTurnId)?.index !== index
      ) {
        return;
      }

      if (shouldPinExecutionPlaceholderToTail(projectedMessage)) {
        tailPlaceholders.push(projectedMessage);
      } else {
        regular.push(projectedMessage);
      }
    });

    return [...regular, ...tailPlaceholders];
  }, [cancellingTurnIds, detachingTurnIds, executionControlByTurnId, finalizedTurnIds, messages, summaries]);
  /**
   * Show the typing-indicator bubble only when a turn is genuinely in flight
   * AND no assistant row has materialised yet for that turn. The bubble
   * disappears as soon as the first ``chat_message_upserted`` lands and the
   * assistant message row joins ``messages`` — at that point the streaming
   * bubble takes over the visual job. We scan the tail of ``messages`` so we
   * cheaply distinguish "user just sent, waiting on LLM" from "assistant
   * already streaming/finalised". Runtime-status rows are ignored: their
   * presence doesn't mean a real reply has started.
   */
  const showPendingBubble = useMemo(() => {
    if (!waitingForReply) {
      return false;
    }
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const msg = messages[i];
      if (msg.role === 'assistant') {
        return false;
      }
      if (msg.role === 'user') {
        return true;
      }
    }
    return false;
  }, [messages, waitingForReply]);

  const transcriptInteractions: TranscriptTimelineInteractions = {
    currentSessionId,
    labelPopoverState,
    labelPopoverDraft,
    labelPopoverRef,
    onSetReplyTarget,
    onOpenImagePreview,
    onCloseLabelPopover,
    onCloseMessageContextMenu,
    onOpenLabelPopover,
    onOpenMessageContextMenu,
    onApplyLabelToMessage,
    onLabelDraftChange,
    onLabelDraftCompositionStart,
    onLabelDraftCompositionEnd,
    recallFeedbackDisabled,
    onStartRecallFeedback,
  };

  return (
    <div
      ref={timelineRef}
      className="min-h-0 flex-1 overflow-y-auto px-2 py-5 scrollbar-thin scrollbar-thumb-[hsl(var(--border)/0.58)] scrollbar-track-transparent"
    >
      <ChatMessageContextMenuOverlay
        messageContextMenu={messageContextMenu}
        messageContextMenuRef={messageContextMenuRef}
        onSetReplyTarget={onSetReplyTarget}
        onCloseMessageContextMenu={onCloseMessageContextMenu}
        onCopyMessage={onCopyMessage}
        onDeleteMessage={onDeleteMessage}
      />
      <div className="mx-auto flex w-full max-w-[1080px] flex-col px-1">
        {projectedMessages.map((projectedMessage) => {
          return projectedMessage.surface !== 'transcript' ? (
            <StatusTimelineRow
              key={projectedMessage.message.id}
              projectedMessage={projectedMessage}
              assistant={assistant}
              shouldReduceMotion={shouldReduceMotion}
              execution={execution}
            />
          ) : (
            <TranscriptTimelineRow
              key={projectedMessage.message.id}
              projectedMessage={projectedMessage}
              assistant={assistant}
              shouldReduceMotion={shouldReduceMotion}
              execution={execution}
              interactions={transcriptInteractions}
              isLastAssistant={projectedMessage.message.id === lastAssistantId}
              isCorrected={correctedMessageIds.has(
                String(projectedMessage.message.messageId || projectedMessage.message.id),
              )}
            />
          );
        })}

        {showPendingBubble && (
          <PendingAssistantBubble
            assistantName={assistantName}
            assistantAvatar={assistantAvatar}
            shouldReduceMotion={shouldReduceMotion}
          />
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};
