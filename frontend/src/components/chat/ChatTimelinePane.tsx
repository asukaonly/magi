import type { RefObject } from 'react';
import { useMemo } from 'react';
import { projectChatTimelineRow, type TurnExecutionControlState } from '@/domain/chat/presentation';
import type { ChatTimelineMessage, ChatTimelineReplyPreview, NormalizedExecutionTraceSummary } from '@/domain/chat/state';
import type { LabelPopoverState, MessageContextMenuState } from '@/hooks/useChatMessageOverlays';
import { ChatMessageContextMenuOverlay } from './ChatMessageContextMenuOverlay';
import { StatusTimelineRow } from './StatusTimelineRow';
import type {
  TimelineAssistantIdentity,
  TimelineAssistantPersona,
  TimelineExecutionBindings,
  TranscriptTimelineInteractions,
} from './TimelineRowShared';
import { TranscriptTimelineRow } from './TranscriptTimelineRow';

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
  };

  return (
    <div ref={timelineRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
      <ChatMessageContextMenuOverlay
        messageContextMenu={messageContextMenu}
        messageContextMenuRef={messageContextMenuRef}
        onSetReplyTarget={onSetReplyTarget}
        onCloseMessageContextMenu={onCloseMessageContextMenu}
        onCopyMessage={onCopyMessage}
        onDeleteMessage={onDeleteMessage}
      />
      {messages.map((msg) => {
        const projectedMessage = projectChatTimelineRow(msg, {
          summaries,
          executionControlByTurnId,
          cancellingTurnIds,
          detachingTurnIds,
          finalizedTurnIds,
        });

        const projectedTurnId = String(projectedMessage.message.turnId || '').trim();
        if (projectedMessage.surface === 'runtime_status' && projectedTurnId && finalizedTurnIds.has(projectedTurnId)) {
          return null;
        }

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
          />
        );
      })}

      <div ref={messagesEndRef} />
    </div>
  );
};