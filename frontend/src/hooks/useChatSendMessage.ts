import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import type { ChatAttachment } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { createClientTurnId, type ChatTimelineReplyPreview } from '@/domain/chat/state';

const USER_ID = DEFAULT_USER_ID;

type UploadableDraftAttachment = {
  file: File;
};

export type PendingTurnPayload = {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
  attachments?: ChatAttachment[];
  replyTo?: ChatTimelineReplyPreview | null;
};

export type UseChatSendMessageOptions = {
  currentSessionId: string | null;
  currentWorkspacePath: string | null | undefined;
  inputValue: string;
  draftAttachments: UploadableDraftAttachment[];
  replyTarget: ChatTimelineReplyPreview | null;
  allowInterjection: boolean;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  setInputValue: (value: string) => void;
  setCurrentSessionId: (sessionId: string | null) => void;
  clearDraftAttachments: () => void;
  clearReplyTarget: () => void;
  onPendingResponseTurn: (turnId: string) => void;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

export function useChatSendMessage({
  currentSessionId,
  currentWorkspacePath,
  inputValue,
  draftAttachments,
  replyTarget,
  allowInterjection,
  appendPendingTurn,
  setInputValue,
  setCurrentSessionId,
  clearDraftAttachments,
  clearReplyTarget,
  onPendingResponseTurn,
  translate,
}: UseChatSendMessageOptions) {
  const [sendingMessage, setSendingMessage] = useState(false);

  const uploadDraftAttachments = useCallback(async (
    sessionId: string,
    turnId: string,
    attachments: UploadableDraftAttachment[],
  ): Promise<ChatAttachment[]> => {
    if (!attachments.length) {
      return [];
    }

    return Promise.all(
      attachments.map((attachment) => messagesApi.uploadAttachment(USER_ID, sessionId, turnId, attachment.file))
    );
  }, []);

  const handleSendMessage = useCallback(async () => {
    const trimmedMessage = inputValue.trim();
    if (!trimmedMessage && draftAttachments.length === 0) {
      toast.warning(translate('chat.emptyInput'));
      return;
    }
    if (!currentSessionId) {
      toast.error(translate('chat.sessionRequired'));
      return;
    }

    const turnId = createClientTurnId();
    const now = Date.now();
    const messageContent = trimmedMessage;

    setSendingMessage(true);
    try {
      const uploadedAttachments = await uploadDraftAttachments(currentSessionId, turnId, draftAttachments);
      appendPendingTurn({
        sessionId: currentSessionId,
        input: messageContent,
        turnId,
        timestamp: now,
        pendingLabel: translate('chat.trace.pending'),
        attachments: uploadedAttachments,
        replyTo: replyTarget,
      });
      setInputValue('');
      clearDraftAttachments();
      clearReplyTarget();
      if (!allowInterjection) {
        onPendingResponseTurn(turnId);
      }

      const result = await messagesApi.sendMessage({
        user_id: USER_ID,
        session_id: currentSessionId,
        message: messageContent,
        attachments: uploadedAttachments,
        reply_to_message_id: replyTarget?.messageId,
        workspace_path: currentWorkspacePath ?? null,
        client_turn_id: turnId,
      });
      if (result.data?.session_id) {
        setCurrentSessionId(String(result.data.session_id));
      }
      window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : translate('chat.sendFailed');
      toast.error(translate('chat.attachments.uploadFailed', { message }));
    } finally {
      setSendingMessage(false);
    }
  }, [
    allowInterjection,
    appendPendingTurn,
    clearDraftAttachments,
    clearReplyTarget,
    currentSessionId,
    currentWorkspacePath,
    draftAttachments,
    inputValue,
    onPendingResponseTurn,
    replyTarget,
    setCurrentSessionId,
    setInputValue,
    translate,
    uploadDraftAttachments,
  ]);

  return {
    sendingMessage,
    handleSendMessage,
  };
}