import type { RefObject } from 'react';
import { buildReplyPreviewFromMessage } from '@/domain/chat/presentation';
import type { ChatTimelineMessage, ChatTimelineReplyPreview } from '@/domain/chat/state';
import type { MessageContextMenuState } from '@/hooks/useChatMessageOverlays';
import { MessageContextMenu } from './MessageContextMenu';

type ChatMessageContextMenuOverlayProps = {
  messageContextMenu: MessageContextMenuState | null;
  messageContextMenuRef: RefObject<HTMLDivElement>;
  onSetReplyTarget: (reply: ChatTimelineReplyPreview | null) => void;
  onCloseMessageContextMenu: () => void;
  onCopyMessage: (message: ChatTimelineMessage, mode: 'markdown' | 'plain') => void;
  onDeleteMessage: (message: ChatTimelineMessage) => void;
};

export const ChatMessageContextMenuOverlay = ({
  messageContextMenu,
  messageContextMenuRef,
  onSetReplyTarget,
  onCloseMessageContextMenu,
  onCopyMessage,
  onDeleteMessage,
}: ChatMessageContextMenuOverlayProps) => {
  if (!messageContextMenu) {
    return null;
  }

  return (
    <MessageContextMenu
      menuRef={messageContextMenuRef}
      x={messageContextMenu.x}
      y={messageContextMenu.y}
      onReply={() => {
        const replyPreview = buildReplyPreviewFromMessage(messageContextMenu.message);
        if (replyPreview) {
          onSetReplyTarget(replyPreview);
        }
        onCloseMessageContextMenu();
      }}
      onCopyMarkdown={() => {
        void onCopyMessage(messageContextMenu.message, 'markdown');
      }}
      onCopyPlain={() => {
        void onCopyMessage(messageContextMenu.message, 'plain');
      }}
      onDelete={() => {
        void onDeleteMessage(messageContextMenu.message);
      }}
    />
  );
};