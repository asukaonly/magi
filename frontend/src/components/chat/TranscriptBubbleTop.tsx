import { FileText, ImagePlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatAttachment } from '@/api';
import {
  formatAttachmentKindLabel,
  formatAttachmentSize,
  resolveHistoryImagePreviewUrl,
} from '@/domain/chat/attachments';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';

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
  const assistantInlineImages = align === 'assistant'
    ? visibleAttachments.filter((attachment) => attachment.kind === 'image')
    : [];
  const renderInlineImageGallery = assistantInlineImages.length === visibleAttachments.length
    && assistantInlineImages.length > 0;

  if (!hasReplyStrip && visibleAttachments.length === 0) {
    return null;
  }

  return (
    <>
      {hasReplyStrip && replyTo ? (
        <div
          className={align === 'user'
            ? 'mb-3 rounded-lg border border-white/70 bg-white/72 px-3 py-2 text-left text-[#5f3427] shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] backdrop-blur-sm'
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
      {visibleAttachments.length > 0 ? (
        renderInlineImageGallery ? (
          <div className="mb-3 grid gap-2">
            {assistantInlineImages.map((attachment) => {
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
                  className="group overflow-hidden rounded-2xl border border-border/50 bg-background text-left shadow-sm transition hover:border-border/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                >
                  {previewUrl ? (
                    <img
                      src={previewUrl}
                      alt={attachment.original_name}
                      className="max-h-[360px] w-full object-cover transition duration-200 group-hover:scale-[1.01]"
                    />
                  ) : (
                    <div className="flex h-40 items-center justify-center bg-muted/40 text-primary">
                      <ImagePlus className="h-8 w-8" />
                    </div>
                  )}
                  <div className="flex items-center justify-between gap-3 px-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-foreground">{attachment.original_name}</div>
                      <div className="truncate text-xs text-muted-foreground">
                        {formatAttachmentKindLabel(attachment, t)}
                        {typeof attachment.size_bytes === 'number' ? ` · ${formatAttachmentSize(attachment.size_bytes)}` : ''}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="mb-3 flex flex-wrap gap-2">
            {visibleAttachments.map((attachment) => {
              const previewUrl = resolveHistoryImagePreviewUrl(currentSessionId, attachment);

              return (
                <div
                  key={attachment.attachment_id}
                  className={align === 'user'
                    ? 'flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-accent-foreground/10 bg-background/90 px-3 py-2 text-foreground'
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
                      <img
                        src={previewUrl}
                        alt={attachment.original_name}
                        className="h-12 w-12 rounded-xl object-cover"
                      />
                    </button>
                  ) : (
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      {attachment.kind === 'image' ? <ImagePlus className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
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
        )
      ) : null}
    </>
  );
};