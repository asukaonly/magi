import type { RefObject } from 'react';
import type { ProjectedTraceEntryPresentation } from '@/domain/chat/presentation';
import type { ChatTimelineMessage, ChatTimelineReplyPreview } from '@/domain/chat/state';
import type { LabelPopoverState } from '@/hooks/useChatMessageOverlays';
import { QuickLabelAction } from './QuickLabelAction';
import { ReplyActionButton } from './ReplyActionButton';
import { TraceEntryButton } from './TraceEntryButton';

const LABEL_EMOJI_OPTIONS = ['😀', '🙂', '😍', '😮', '😂', '😎', '🥹', '🙏', '🔥', '👍'];
const LABEL_POPOVER_WIDTH = 336;
const LABEL_POPOVER_HEIGHT = 272;

type TranscriptHeaderActionsProps = {
  message: ChatTimelineMessage;
  replyPreview: ChatTimelineReplyPreview | null;
  canQuickLabel: boolean;
  showHeaderTraceEntry: boolean;
  traceEntry: ProjectedTraceEntryPresentation;
  traceEntryLabel: string;
  labelPopoverState: LabelPopoverState | null;
  labelPopoverDraft: string;
  labelPopoverRef: RefObject<HTMLDivElement>;
  onSetReplyTarget: (reply: ChatTimelineReplyPreview | null) => void;
  onOpenTraceDrawer: (turnId: string) => void;
  onCloseLabelPopover: () => void;
  onCloseMessageContextMenu: () => void;
  onOpenLabelPopover: (messageId: string, position: { x: number; y: number }) => void;
  onApplyLabelToMessage: (message: ChatTimelineMessage, nextLabel: { kind: string; text: string }) => void;
  onLabelDraftChange: (value: string) => void;
  onLabelDraftCompositionStart: () => void;
  onLabelDraftCompositionEnd: (value: string) => void;
};

const getLabelPopoverPosition = (rect: DOMRect): { x: number; y: number } => {
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280;
  const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 800;
  const alignedLeft = Math.max(16, Math.min(rect.left, viewportWidth - LABEL_POPOVER_WIDTH - 16));
  const belowTop = rect.bottom + 8;
  const aboveTop = rect.top - LABEL_POPOVER_HEIGHT - 8;

  return {
    x: alignedLeft,
    y: belowTop + LABEL_POPOVER_HEIGHT <= viewportHeight - 16
      ? belowTop
      : Math.max(16, aboveTop),
  };
};

export const TranscriptHeaderActions = ({
  message,
  replyPreview,
  canQuickLabel,
  showHeaderTraceEntry,
  traceEntry,
  traceEntryLabel,
  labelPopoverState,
  labelPopoverDraft,
  labelPopoverRef,
  onSetReplyTarget,
  onOpenTraceDrawer,
  onCloseLabelPopover,
  onCloseMessageContextMenu,
  onOpenLabelPopover,
  onApplyLabelToMessage,
  onLabelDraftChange,
  onLabelDraftCompositionStart,
  onLabelDraftCompositionEnd,
}: TranscriptHeaderActionsProps) => {
  const isQuickLabelOpen = labelPopoverState?.messageId === message.messageId;

  return (
    <>
      {replyPreview ? (
        <ReplyActionButton
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onSetReplyTarget(replyPreview);
          }}
        />
      ) : null}
      {canQuickLabel ? (
        <QuickLabelAction
          isOpen={isQuickLabelOpen}
          draft={labelPopoverDraft}
          popoverRef={labelPopoverRef}
          position={labelPopoverState ? { x: labelPopoverState.x, y: labelPopoverState.y } : null}
          emojiOptions={LABEL_EMOJI_OPTIONS}
          onToggle={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onCloseMessageContextMenu();
            if (isQuickLabelOpen) {
              onCloseLabelPopover();
              return;
            }
            const triggerRect = (event.currentTarget as HTMLButtonElement).getBoundingClientRect();
            onOpenLabelPopover(String(message.messageId), getLabelPopoverPosition(triggerRect));
          }}
          onEmojiSelect={(emoji) => {
            void onApplyLabelToMessage(message, { kind: 'emoji', text: emoji });
          }}
          onDraftChange={onLabelDraftChange}
          onDraftCompositionStart={onLabelDraftCompositionStart}
          onDraftCompositionEnd={onLabelDraftCompositionEnd}
          onApplyDraft={() => {
            void onApplyLabelToMessage(message, {
              kind: 'text',
              text: labelPopoverDraft.trim(),
            });
          }}
        />
      ) : null}
      {showHeaderTraceEntry ? (
        <TraceEntryButton
          traceEntry={traceEntry}
          label={traceEntryLabel}
          onOpenTraceDrawer={onOpenTraceDrawer}
        />
      ) : null}
    </>
  );
};