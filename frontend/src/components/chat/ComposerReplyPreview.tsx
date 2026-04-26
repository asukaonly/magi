import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';

type ComposerReplyPreviewProps = {
  target: ChatTimelineReplyPreview;
  onCancel: () => void;
};

export const ComposerReplyPreview = ({ target, onCancel }: ComposerReplyPreviewProps) => {
  const { t } = useTranslation();

  return (
    <div
      data-testid="chat-composer-reply-preview"
      className="mx-5 mt-4 rounded-xl border border-border/50 bg-muted/25 px-3 py-2"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            {target.role === 'assistant' ? t('chat.reply.assistant') : t('chat.reply.user')}
          </div>
          <div className="mt-1 line-clamp-2 text-sm text-foreground/85">
            {target.contentExcerpt}
          </div>
        </div>
        <button
          type="button"
          aria-label={t('chat.reply.cancel')}
          onClick={onCancel}
          className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};