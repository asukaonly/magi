import type { ClipboardEventHandler, KeyboardEventHandler, Ref } from 'react';
import { ArrowUp, Loader2, Square } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { SessionSafetyControl } from '@/components/control';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import { ComposerAttachmentMenu } from './ComposerAttachmentMenu';
import { ComposerDraftAttachments } from './ComposerDraftAttachments';
import { ComposerReplyPreview } from './ComposerReplyPreview';
import { ContextUsageRing } from './ContextUsageRing';

type ComposerDraftAttachmentItem = {
  id: string;
  kind: 'image' | 'file';
  name: string;
  size: number;
  previewUrl?: string;
};

export type ChatComposerShellProps = {
  composerRef: Ref<HTMLDivElement>;
  replyTarget: ChatTimelineReplyPreview | null;
  onCancelReply: () => void;
  attachments: ComposerDraftAttachmentItem[];
  onRemoveAttachment: (attachmentId: string) => void;
  inputValue: string;
  onInputChange: (value: string) => void;
  onCompositionStart: () => void;
  onCompositionEnd: () => void;
  onKeyDown: KeyboardEventHandler<HTMLTextAreaElement>;
  onPaste: ClipboardEventHandler<HTMLTextAreaElement>;
  waitingForReply: boolean;
  attachmentMenuOpen: boolean;
  coreModelSupportsVision: boolean;
  onToggleAttachmentMenu: () => void;
  onPickImage: () => void;
  onPickFile: () => void;
  sessionId: string | null;
  sendingMessage: boolean;
  onPrimaryAction: () => void;
};

export const ChatComposerShell = ({
  composerRef,
  replyTarget,
  onCancelReply,
  attachments,
  onRemoveAttachment,
  inputValue,
  onInputChange,
  onCompositionStart,
  onCompositionEnd,
  onKeyDown,
  onPaste,
  waitingForReply,
  attachmentMenuOpen,
  coreModelSupportsVision,
  onToggleAttachmentMenu,
  onPickImage,
  onPickFile,
  sessionId,
  sendingMessage,
  onPrimaryAction,
}: ChatComposerShellProps) => {
  const { t } = useTranslation();

  return (
    <div
      ref={composerRef}
      className="rounded-2xl border border-border/45 bg-background shadow-[0_8px_24px_rgba(15,23,42,0.04)]"
    >
      {replyTarget ? (
        <ComposerReplyPreview
          target={replyTarget}
          onCancel={onCancelReply}
        />
      ) : null}
      <ComposerDraftAttachments
        attachments={attachments}
        hasReplyTarget={Boolean(replyTarget)}
        onRemove={onRemoveAttachment}
      />

      <div
        data-testid="chat-composer-input"
        className={attachments.length > 0 ? 'px-5 pb-0 pt-2.5' : 'px-5 pb-0 pt-3'}
      >
        <AutoResizeTextarea
          value={inputValue}
          onChange={(event) => onInputChange(event.target.value)}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          placeholder={waitingForReply ? t('chat.waitingForReply') : t('chat.inputPlaceholder')}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          disabled={waitingForReply}
          minHeight={88}
          className="max-h-72 resize-none border-0 bg-transparent p-0 text-sm leading-6 shadow-none placeholder:text-muted-foreground/55 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:bg-transparent disabled:text-muted-foreground"
        />
      </div>
      <div
        data-testid="chat-composer-toolbar"
        className="flex items-center justify-between px-2 pb-0 pt-1"
      >
        <div className="flex items-center gap-1">
          <ComposerAttachmentMenu
            isOpen={attachmentMenuOpen}
            coreModelSupportsVision={coreModelSupportsVision}
            onToggle={onToggleAttachmentMenu}
            onPickImage={onPickImage}
            onPickFile={onPickFile}
          />
          <div className="relative">
            <SessionSafetyControl sessionId={sessionId} />
          </div>
          <ContextUsageRing sessionId={sessionId} />
        </div>
        <div data-testid="chat-composer-primary-action" className="self-end pb-2">
          <button
            type="button"
            onClick={onPrimaryAction}
            disabled={sendingMessage}
            className="flex h-[34px] w-[34px] items-center justify-center rounded-lg bg-foreground/88 text-background transition-colors hover:bg-foreground/96 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
            aria-label={waitingForReply ? t('chat.stop') : t('chat.send')}
            title={waitingForReply ? t('chat.stop') : t('chat.send')}
          >
            {sendingMessage ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : waitingForReply ? (
              <Square className="h-3.5 w-3.5" />
            ) : (
              <ArrowUp className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
};