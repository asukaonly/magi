import type { ChatAttachment } from '@/api';
import { DEFAULT_USER_ID } from '@/constants';
import { getRuntimeConfig } from '@/runtime/config';

export const formatAttachmentSize = (size: number): string => {
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

export const formatAttachmentKindLabel = (attachment: ChatAttachment, t: (key: string) => string): string => {
  if (attachment.kind === 'image') {
    return t('chat.attachments.addImage');
  }
  return t('chat.attachments.addFile');
};

export const resolveHistoryImagePreviewUrl = (
  sessionId: string | null | undefined,
  attachment: ChatAttachment,
  userId: string = DEFAULT_USER_ID,
): string | null => {
  if (attachment.kind !== 'image') {
    return null;
  }
  const normalizedSessionId = String(sessionId || '').trim();
  const attachmentId = String(attachment.attachment_id || '').trim();
  if (!normalizedSessionId || !attachmentId) {
    return null;
  }
  const apiBaseUrl = getRuntimeConfig().apiBaseUrl.replace(/\/+$/, '');
  return `${apiBaseUrl}/messages/session/${encodeURIComponent(normalizedSessionId)}/attachments/${encodeURIComponent(attachmentId)}/content?user_id=${encodeURIComponent(userId)}`;
};