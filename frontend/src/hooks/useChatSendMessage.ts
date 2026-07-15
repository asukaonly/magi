import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { messagesApi } from '@/api';
import type { ChatAttachment } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { createClientTurnId, type ChatTimelineReplyPreview } from '@/domain/chat/state';
import {
  toRecallFeedbackReplyPreview,
  toRecallFeedbackRequest,
  type RecallFeedbackDraft,
} from '@/domain/chat/recall-feedback';
import type { ComposerDraftItem } from './useChatDraftAttachments';
import { isFileDraftAttachment, isMcpDraftAttachment } from './useChatDraftAttachments';

const USER_ID = DEFAULT_USER_ID;

export type PendingTurnPayload = {
  sessionId: string;
  input: string;
  turnId: string;
  timestamp: number;
  pendingLabel: string;
  attachments?: ChatAttachment[];
  replyTo?: ChatTimelineReplyPreview | null;
  payload?: Record<string, unknown> | null;
};

export type PendingAskSendContext = {
  requestId: string;
  sessionId: string;
  messageId: string | null;
  question: string;
};

export type PendingAskAnswerPayload = PendingAskSendContext & {
  answer: string;
  timestamp: number;
};

export type UseChatSendMessageOptions = {
  currentSessionId: string | null;
  currentWorkspacePath: string | null | undefined;
  inputValue: string;
  draftAttachments: ComposerDraftItem[];
  replyTarget: ChatTimelineReplyPreview | null;
  allowInterjection: boolean;
  pendingAsk: PendingAskSendContext | null;
  recallFeedbackDraft: RecallFeedbackDraft | null;
  appendPendingTurn: (payload: PendingTurnPayload) => void;
  removePendingMessage: (sessionId: string, messageId: string) => void;
  setInputValue: (value: string) => void;
  setCurrentSessionId: (sessionId: string | null) => void;
  clearDraftAttachments: () => void;
  clearReplyTarget: () => void;
  clearRecallFeedback: () => void;
  onPendingResponseTurn: (turnId: string) => void;
  onAskAnswered: (answer: PendingAskAnswerPayload) => void;
  translate: (key: string, options?: Record<string, unknown>) => string;
};

const mcpResourceToChatAttachment = (
  item: Extract<ComposerDraftItem, { kind: 'mcp_resource' }>,
): ChatAttachment => ({
  attachment_id: item.id,
  kind: 'mcp_resource',
  original_name: item.name || item.uri,
  mime_type: item.mimeType,
  server_id: item.serverId,
  uri: item.uri,
});

export function useChatSendMessage({
  currentSessionId,
  currentWorkspacePath,
  inputValue,
  draftAttachments,
  replyTarget,
  allowInterjection,
  pendingAsk,
  recallFeedbackDraft,
  appendPendingTurn,
  removePendingMessage,
  setInputValue,
  setCurrentSessionId,
  clearDraftAttachments,
  clearReplyTarget,
  clearRecallFeedback,
  onPendingResponseTurn,
  onAskAnswered,
  translate,
}: UseChatSendMessageOptions) {
  const [sendingMessage, setSendingMessage] = useState(false);

  const uploadDraftAttachments = useCallback(async (
    sessionId: string,
    turnId: string,
    drafts: ComposerDraftItem[],
  ): Promise<ChatAttachment[]> => {
    if (!drafts.length) {
      return [];
    }

    const fileDrafts = drafts.filter(isFileDraftAttachment);
    const mcpDrafts = drafts.filter(isMcpDraftAttachment);

    const uploaded = fileDrafts.length === 0
      ? []
      : await Promise.all(
        fileDrafts.map((draft) =>
          messagesApi.uploadAttachment(USER_ID, sessionId, turnId, draft.file),
        ),
      );

    return [...uploaded, ...mcpDrafts.map(mcpResourceToChatAttachment)];
  }, []);

  const handleSendMessage = useCallback(async () => {
    const trimmedMessage = inputValue.trim();
    if (recallFeedbackDraft && !trimmedMessage) {
      toast.warning(translate('chat.emptyInput'));
      return;
    }
    if (!recallFeedbackDraft && !trimmedMessage && draftAttachments.length === 0) {
      toast.warning(translate('chat.emptyInput'));
      return;
    }
    if (!currentSessionId) {
      toast.error(translate('chat.sessionRequired'));
      return;
    }

    if (pendingAsk) {
      if (recallFeedbackDraft) {
        toast.warning(translate('chat.recallFeedback.pendingAskBlocked'));
        return;
      }
      if (!trimmedMessage) {
        toast.warning(translate('chat.emptyInput'));
        return;
      }
      if (draftAttachments.length > 0) {
        toast.warning(translate('chat.askAttachmentsUnsupported', { defaultValue: 'Remove attachments before answering this question.' }));
        return;
      }

      setSendingMessage(true);
      try {
        const result = await messagesApi.sendMessage({
          user_id: USER_ID,
          session_id: currentSessionId,
          message: trimmedMessage,
          workspace_path: currentWorkspacePath ?? null,
        });
        if (result.success === false) {
          throw new Error(result.message || translate('chat.sendFailed'));
        }
        if (result.data?.session_id) {
          setCurrentSessionId(String(result.data.session_id));
        }
        setInputValue('');
        clearDraftAttachments();
        clearReplyTarget();
        onAskAnswered({
          ...pendingAsk,
          answer: trimmedMessage,
          timestamp: Date.now(),
        });
        window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : translate('chat.sendFailed');
        toast.error(message);
      } finally {
        setSendingMessage(false);
      }
      return;
    }

    if (recallFeedbackDraft) {
      const turnId = createClientTurnId();
      const now = Date.now();
      const feedbackRequest = toRecallFeedbackRequest(recallFeedbackDraft);
      const feedbackReply = toRecallFeedbackReplyPreview(recallFeedbackDraft);

      setSendingMessage(true);
      try {
        appendPendingTurn({
          sessionId: currentSessionId,
          input: trimmedMessage,
          turnId,
          timestamp: now,
          pendingLabel: translate('chat.trace.pending'),
          replyTo: feedbackReply,
          payload: { recall_feedback: feedbackRequest },
        });
        const result = await messagesApi.sendMessage({
          user_id: USER_ID,
          session_id: currentSessionId,
          message: trimmedMessage,
          reply_to_message_id: recallFeedbackDraft.targetMessageId,
          workspace_path: currentWorkspacePath ?? null,
          client_turn_id: turnId,
          recall_feedback: feedbackRequest,
        });
        if (result.success === false) {
          throw new Error(result.message || translate('chat.sendFailed'));
        }
        if (result.data?.session_id) {
          setCurrentSessionId(String(result.data.session_id));
        }
        if (!allowInterjection) {
          onPendingResponseTurn(turnId);
        }
        clearRecallFeedback();
        window.dispatchEvent(new Event(APP_EVENTS.SESSION_SYNC));
      } catch (error: unknown) {
        removePendingMessage(currentSessionId, `${turnId}-user`);
        const message = error instanceof Error ? error.message : translate('chat.sendFailed');
        toast.error(message);
      } finally {
        setSendingMessage(false);
      }
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
    clearRecallFeedback,
    clearReplyTarget,
    currentSessionId,
    currentWorkspacePath,
    draftAttachments,
    inputValue,
    onAskAnswered,
    onPendingResponseTurn,
    pendingAsk,
    recallFeedbackDraft,
    removePendingMessage,
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
