import type { RefObject } from 'react';
import { useTranslation } from 'react-i18next';

type MessageContextMenuProps = {
  menuRef: RefObject<HTMLDivElement>;
  x: number;
  y: number;
  onReply: () => void;
  onCopyMarkdown: () => void;
  onCopyPlain: () => void;
  onDelete: () => void;
};

export const MessageContextMenu = ({
  menuRef,
  x,
  y,
  onReply,
  onCopyMarkdown,
  onCopyPlain,
  onDelete,
}: MessageContextMenuProps) => {
  const { t } = useTranslation();

  return (
    <div
      ref={menuRef}
      data-testid="chat-message-context-menu"
      className="fixed z-[90] min-w-[180px] rounded-lg border border-border/70 bg-background/95 p-1.5 shadow-[0_14px_36px_rgba(15,23,42,0.16)] backdrop-blur"
      style={{ left: x, top: y }}
    >
      <button
        type="button"
        onClick={onReply}
        className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted/70"
      >
        {t('chat.context.reply')}
      </button>
      <button
        type="button"
        onClick={onCopyMarkdown}
        className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted/70"
      >
        {t('chat.context.copyMarkdown')}
      </button>
      <button
        type="button"
        onClick={onCopyPlain}
        className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted/70"
      >
        {t('chat.context.copyPlain')}
      </button>
      <button
        type="button"
        onClick={onDelete}
        className="flex w-full items-center rounded-md px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
      >
        {t('chat.context.delete')}
      </button>
    </div>
  );
};