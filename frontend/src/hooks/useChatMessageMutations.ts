import { useCallback } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import {
  normalizeMessageLabel,
  type ChatTimelineMessage,
  type ChatTimelineMessageLabel,
} from '@/domain/chat/state';
import { readCodeAgentDelegations } from '@/domain/chat/delegations';
import type { PendingResponseTurnIdentity } from '@/domain/chat/turn-completion';
import {
  retireRealtimeChatDelegation,
  retireRealtimeChatMessage,
} from '@/realtime/chat-projection-retirement';
import { useDelegationsStore } from '@/stores/delegations-store';

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
  clearRetryableTurn: (sessionId: string, turnId: string) => void;
  clearPendingResponseTurn: (expected?: Partial<PendingResponseTurnIdentity>) => void;
  clearComposerReferenceToMessage: (messageId: string) => void;
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
  clearRetryableTurn,
  clearPendingResponseTurn,
  clearComposerReferenceToMessage,
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
      const result = await messagesApi.deleteMessage(
        USER_ID,
        currentSessionId,
        messageId,
      );
      if (
        !result.success
        || String(result.session_id || '').trim() !== currentSessionId
        || String(result.deleted_message_id || '').trim() !== messageId
      ) {
        throw new Error('Message delete request was not completed');
      }
      retireRealtimeChatMessage(currentSessionId, message);
      for (const { delegationId } of readCodeAgentDelegations(message.payload)) {
        retireRealtimeChatDelegation(currentSessionId, delegationId);
        useDelegationsStore.getState().remove(currentSessionId, delegationId);
      }
      if (message.turnId) {
        const delegationIdsForTurn = Object.values(
          useDelegationsStore.getState().delegationsBySession[currentSessionId]
          || {},
        )
          .filter((card) => card.turn_id === message.turnId)
          .map((card) => card.delegation_id);
        for (const turnDelegationId of delegationIdsForTurn) {
          retireRealtimeChatDelegation(
            currentSessionId,
            turnDelegationId,
          );
          useDelegationsStore
            .getState()
            .remove(currentSessionId, turnDelegationId);
        }
      }
      removeMessage(currentSessionId, messageId);
      clearComposerReferenceToMessage(messageId);
      if (message.turnId) {
        clearRetryableTurn(currentSessionId, message.turnId);
        clearPendingResponseTurn({
          sessionId: currentSessionId,
          turnId: message.turnId,
        });
      }
      closeMessageContextMenu();
      if (activeLabelMessageId === messageId) {
        closeLabelPopover();
      }
      if (result.cleanup_pending) {
        toast.warning(translate('chat.context.deleteCleanupPending'));
      }
    } catch {
      toast.error(translate('chat.context.deleteFailed'));
    }
  }, [
    activeLabelMessageId,
    clearPendingResponseTurn,
    clearComposerReferenceToMessage,
    clearRetryableTurn,
    closeLabelPopover,
    closeMessageContextMenu,
    currentSessionId,
    removeMessage,
    translate,
  ]);

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
