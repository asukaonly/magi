import { FileText, Network, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatAttachmentSize } from '@/domain/chat/attachments';

type ComposerDraftAttachmentItem =
  | {
    id: string;
    kind: 'image' | 'file';
    name: string;
    size: number;
    previewUrl?: string;
  }
  | {
    id: string;
    kind: 'mcp_resource';
    name: string;
    serverId: string;
    uri: string;
  };

type ComposerDraftAttachmentsProps = {
  attachments: ComposerDraftAttachmentItem[];
  hasReplyTarget: boolean;
  onRemove: (attachmentId: string) => void;
};

export const ComposerDraftAttachments = ({
  attachments,
  hasReplyTarget,
  onRemove,
}: ComposerDraftAttachmentsProps) => {
  const { t } = useTranslation();

  if (!attachments.length) {
    return null;
  }

  return (
    <div
      data-testid="chat-composer-attachments"
      className={`flex flex-wrap gap-2 px-5 ${hasReplyTarget ? 'pt-3' : 'pt-4'}`}
    >
      {attachments.map((attachment) => {
        if (attachment.kind === 'mcp_resource') {
          return (
            <div
              key={attachment.id}
              data-testid="composer-mcp-attachment"
              className="flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-border/55 bg-muted/30 px-3 py-2"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Network className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground">{attachment.name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {attachment.serverId} · {attachment.uri}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onRemove(attachment.id)}
                aria-label={t('chat.attachments.remove')}
                className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        }

        return (
          <div
            key={attachment.id}
            className="flex min-w-[180px] max-w-[260px] items-center gap-3 rounded-xl border border-border/55 bg-muted/30 px-3 py-2"
          >
            {attachment.kind === 'image' && attachment.previewUrl ? (
              <img
                src={attachment.previewUrl}
                alt={attachment.name}
                className="h-11 w-11 shrink-0 rounded-lg object-cover"
              />
            ) : (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <FileText className="h-5 w-5" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-foreground">{attachment.name}</div>
              <div className="text-xs text-muted-foreground">{formatAttachmentSize(attachment.size)}</div>
            </div>
            <button
              type="button"
              onClick={() => onRemove(attachment.id)}
              aria-label={t('chat.attachments.remove')}
              className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
