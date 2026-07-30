import { FileText, ImagePlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatAttachment } from '@/api';
import {
  formatAttachmentKindLabel,
  formatAttachmentSize,
  resolveHistoryImagePreviewUrl,
} from '@/domain/chat/attachments';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import { ProtectedImage } from '@/components/media/ProtectedImage';

type TranscriptBubbleTopProps = {
  align: 'user' | 'assistant';
  replyTo?: ChatTimelineReplyPreview | null;
  attachments?: ChatAttachment[];
  currentSessionId?: string | null;
  showReplyStrip: boolean;
  showAttachments: boolean;
  onOpenImagePreview: (payload: { name: string; url: string }) => void;
};

export const TranscriptBubbleTop = ({
  align,
  replyTo,
  attachments,
  currentSessionId,
  showReplyStrip,
  showAttachments,
  onOpenImagePreview,
}: TranscriptBubbleTopProps) => {
  const { t } = useTranslation();
  const hasReplyStrip = showReplyStrip && Boolean(replyTo);
  const visibleAttachments = showAttachments && Array.isArray(attachments) ? attachments : [];
  const imageAttachments = visibleAttachments.filter((attachment) => attachment.kind === 'image');
  const fileAttachments = visibleAttachments.filter((attachment) => attachment.kind !== 'image');

  if (!hasReplyStrip && visibleAttachments.length === 0) {
    return null;
  }

  return (
    <>
      {hasReplyStrip && replyTo ? (
        <div
          className={align === 'user'
            ? 'mb-3 rounded-lg border border-border/45 bg-background/80 px-3 py-2 text-left text-foreground'
            : 'mb-3 rounded-lg border border-border/45 bg-background/80 px-3 py-2 text-left text-foreground'}
        >
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            {replyTo.role === 'assistant' ? t('chat.reply.assistant') : t('chat.reply.user')}
          </div>
          <div className="mt-1 line-clamp-2 text-xs leading-5 text-foreground/85">
            {replyTo.contentExcerpt}
          </div>
        </div>
      ) : null}
      {imageAttachments.length > 0 ? (
        <div className="mb-3 grid gap-2">
          {imageAttachments.map((attachment) => {
            const previewUrl = resolveHistoryImagePreviewUrl(currentSessionId, attachment);

            return (
              <button
                key={attachment.attachment_id}
                type="button"
                onClick={() => {
                  if (!previewUrl) {
                    return;
                  }
                  onOpenImagePreview({
                    name: attachment.original_name,
                    url: previewUrl,
                  });
                }}
                aria-label={t('chat.attachments.openPreview')}
                className={align === 'user'
                  ? 'group block w-[340px] max-w-full overflow-hidden rounded-xl border border-border/45 bg-background text-left shadow-sm transition hover:border-border/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 sm:w-[380px]'
                  : 'group block w-[340px] max-w-full overflow-hidden rounded-xl border border-border/45 bg-background text-left shadow-sm transition hover:border-border/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 sm:w-[380px]'}
              >
                {previewUrl ? (
                  <ProtectedImage
                    src={previewUrl}
                    alt={attachment.original_name}
                    className="block max-h-[420px] min-h-24 w-full object-contain transition duration-200 group-hover:scale-[1.006]"
                  />
                ) : (
                  <div className="flex h-48 items-center justify-center bg-muted/40 text-primary">
                    <ImagePlus className="h-8 w-8" />
                  </div>
                )}
              </button>
            );
          })}
        </div>
      ) : null}
      {fileAttachments.length > 0 ? (
        <div className="mb-3 flex flex-wrap gap-2">
          {fileAttachments.map((attachment) => {
            const previewUrl = resolveHistoryImagePreviewUrl(currentSessionId, attachment);

            return (
              <div
                key={attachment.attachment_id}
                className={align === 'user'
                  ? 'flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-border/55 bg-background px-3 py-2 text-foreground'
                  : 'flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-border/55 bg-background px-3 py-2 text-foreground'}
              >
                {previewUrl ? (
                  <button
                    type="button"
                    onClick={() => onOpenImagePreview({
                      name: attachment.original_name,
                      url: previewUrl,
                    })}
                    aria-label={t('chat.attachments.openPreview')}
                    className="shrink-0 rounded-xl transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  >
                    <ProtectedImage
                      src={previewUrl}
                      alt={attachment.original_name}
                      className="h-12 w-12 rounded-xl object-cover"
                    />
                  </button>
                ) : (
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <FileText className="h-5 w-5" />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-foreground">{attachment.original_name}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {formatAttachmentKindLabel(attachment, t)}
                    {typeof attachment.size_bytes === 'number' ? ` · ${formatAttachmentSize(attachment.size_bytes)}` : ''}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </>
  );
};
