import { useCallback } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import {
  normalizeMessageLabel,
  type ChatTimelineMessage,
  type ChatTimelineMessageLabel,
} from '@/domain/chat/state';

const USER_ID = DEFAULT_USER_ID;

type MessageLabelPayload = {
  kind: string;
  text: string;
};

type UseChatMessageMutationsOptions = {
  currentSessionId: string | null;
  activeLabelMessageId: string | null;
  applyMessageLabel: (sessionId: string, messageId: string, label: ChatTimelineMessageLabel) => void;
  removeMessage: (sessionId: string, messageId: string) => void;
  closeLabelPopover: () => void;
  closeMessageContextMenu: () => void;
  normalizeCopyText: (content: string) => string;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

export function useChatMessageMutations({
  currentSessionId,
  activeLabelMessageId,
  applyMessageLabel,
  removeMessage,
  closeLabelPopover,
  closeMessageContextMenu,
  normalizeCopyText,
  translate,
}: UseChatMessageMutationsOptions) {
  const applyLabelToMessage = useCallback(async (
    message: ChatTimelineMessage,
    nextLabel: MessageLabelPayload,
  ) => {
    const messageId = String(message.messageId || '').trim();
    if (!currentSessionId || !messageId) {
      return;
    }

    try {
      const response = await messagesApi.labelMessage(USER_ID, currentSessionId, messageId, {
        kind: nextLabel.kind,
        text: nextLabel.text,
        applied_by: 'user',
        source: 'manual',
      });
      const normalizedLabel = normalizeMessageLabel(response.data?.label);
      if (!normalizedLabel) {
        throw new Error('missing_label');
      }

      applyMessageLabel(currentSessionId, messageId, normalizedLabel);
      closeLabelPopover();
    } catch {
      toast.error(translate('chat.label.applyFailed'));
    }
  }, [applyMessageLabel, closeLabelPopover, currentSessionId, translate]);

  const handleDeleteMessage = useCallback(async (message: ChatTimelineMessage) => {
    const messageId = String(message.messageId || '').trim();
    if (!currentSessionId || !messageId) {
      return;
    }

    try {
      await messagesApi.deleteMessage(USER_ID, currentSessionId, messageId);
      removeMessage(currentSessionId, messageId);
      closeMessageContextMenu();
      if (activeLabelMessageId === messageId) {
        closeLabelPopover();
      }
    } catch {
      toast.error(translate('chat.context.deleteFailed'));
    }
  }, [activeLabelMessageId, closeLabelPopover, closeMessageContextMenu, currentSessionId, removeMessage, translate]);

  const handleCopyMessage = useCallback(async (
    message: ChatTimelineMessage,
    mode: 'markdown' | 'plain',
  ) => {
    try {
      const text = mode === 'markdown' ? message.content : normalizeCopyText(message.content);
      await navigator.clipboard.writeText(text);
      closeMessageContextMenu();
    } catch {
      toast.error(translate('chat.context.copyFailed'));
    }
  }, [closeMessageContextMenu, normalizeCopyText, translate]);

  return {
    applyLabelToMessage,
    handleDeleteMessage,
    handleCopyMessage,
  };
}