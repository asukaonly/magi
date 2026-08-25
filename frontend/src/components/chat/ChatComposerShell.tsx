import type { ClipboardEventHandler, KeyboardEventHandler, ReactNode, Ref } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { SessionSafetyControl } from '@/components/control';
import type { ChatTimelineReplyPreview } from '@/domain/chat/state';
import type { RecallFeedbackDraft } from '@/domain/chat/recall-feedback';
import { ComposerAttachmentMenu } from './ComposerAttachmentMenu';
import { ComposerDraftAttachments } from './ComposerDraftAttachments';
import { ComposerReplyPreview } from './ComposerReplyPreview';
import { ContextUsageRing } from './ContextUsageRing';
import { ComposerRecallFeedbackBanner } from './ComposerRecallFeedbackBanner';
import {
  ComposerReasoningControl,
} from './ComposerReasoningControl';
import type { ReasoningPreference } from '@/domain/chat/reasoning';

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

export type ChatComposerShellProps = {
  composerRef: Ref<HTMLDivElement>;
  textareaRef?: Ref<HTMLTextAreaElement>;
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
  answeringAsk?: boolean;
  choiceOnlyAsk?: boolean;
  validChoiceSelected?: boolean;
  inputPlaceholder?: string;
  attachmentsDisabled?: boolean;
  waitingForReply: boolean;
  attachmentMenuOpen: boolean;
  coreModelSupportsVision: boolean;
  coreModelContextWindow: number | null;
  onToggleAttachmentMenu: () => void;
  onPickImage: () => void;
  onPickFile: () => void;
  sessionId: string | null;
  sendingMessage: boolean;
  stoppingReply?: boolean;
  onPrimaryAction: () => void;
  recallFeedbackDraft?: RecallFeedbackDraft | null;
  onCancelRecallFeedback?: () => void;
  onConvertRecallFeedbackToNormal?: () => void;
  reasoningPreference: ReasoningPreference;
  onReasoningPreferenceChange: (value: ReasoningPreference) => void;
  /** Inline controls rendered directly above the textarea. */
  askAnswerSlot?: ReactNode;
  /** Picker(s) rendered absolute-positioned above the input area. */
  pickerSlot?: ReactNode;
};

export const ChatComposerShell = ({
  composerRef,
  textareaRef,
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
  answeringAsk = false,
  choiceOnlyAsk = false,
  validChoiceSelected = false,
  inputPlaceholder,
  attachmentsDisabled = false,
  waitingForReply,
  attachmentMenuOpen,
  coreModelSupportsVision,
  coreModelContextWindow,
  onToggleAttachmentMenu,
  onPickImage,
  onPickFile,
  sessionId,
  sendingMessage,
  stoppingReply = false,
  onPrimaryAction,
  recallFeedbackDraft = null,
  onCancelRecallFeedback,
  onConvertRecallFeedbackToNormal,
  reasoningPreference,
  onReasoningPreferenceChange,
  askAnswerSlot,
  pickerSlot,
}: ChatComposerShellProps) => {
  const { t } = useTranslation();
  const feedbackMode = recallFeedbackDraft !== null;
  const effectiveWaitingForReply = waitingForReply && !feedbackMode;
  const inputDisabled = effectiveWaitingForReply || choiceOnlyAsk;

  return (
    <div
      ref={composerRef}
      className="rounded-xl bg-[hsl(var(--composer-background)/0.94)] shadow-[0_18px_48px_hsl(var(--foreground)/0.08),inset_0_0_0_1px_hsl(var(--composer-border)/0.38)] backdrop-blur-sm"
    >
      {recallFeedbackDraft && onCancelRecallFeedback && onConvertRecallFeedbackToNormal ? (
        <ComposerRecallFeedbackBanner
          draft={recallFeedbackDraft}
          onCancel={onCancelRecallFeedback}
          onConvertToNormal={onConvertRecallFeedbackToNormal}
        />
      ) : null}
      {replyTarget && !feedbackMode ? (
        <ComposerReplyPreview
          target={replyTarget}
          onCancel={onCancelReply}
        />
      ) : null}
      {!feedbackMode ? (
        <ComposerDraftAttachments
          attachments={attachments}
          hasReplyTarget={Boolean(replyTarget)}
          onRemove={onRemoveAttachment}
        />
      ) : null}

      <div
        data-testid="chat-composer-input"
        className={`relative ${attachments.length > 0 ? 'px-5 pb-0 pt-2.5' : 'px-5 pb-0 pt-3.5'}`}
      >
        {askAnswerSlot}
        {pickerSlot}
        <AutoResizeTextarea
          ref={textareaRef}
          value={inputValue}
          onChange={(event) => onInputChange(event.target.value)}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          placeholder={effectiveWaitingForReply
            ? t('chat.waitingForReply')
            : choiceOnlyAsk
              ? t('chat.askChoiceOnlyPlaceholder')
            : feedbackMode
              ? t('chat.recallFeedback.inputPlaceholder')
              : inputPlaceholder || t('chat.inputPlaceholder')}
          onKeyDown={onKeyDown}
          onPaste={feedbackMode || answeringAsk ? undefined : onPaste}
          disabled={inputDisabled}
          minHeight={72}
          className="max-h-64 resize-none border-0 bg-transparent p-0 text-[15px] leading-7 shadow-none placeholder:text-muted-foreground/48 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:bg-transparent disabled:text-muted-foreground"
        />
      </div>
      <div
        data-testid="chat-composer-toolbar"
        className="flex items-end justify-between px-3 pb-3 pt-1"
      >
        <div className="flex items-center gap-1">
          <ComposerAttachmentMenu
            isOpen={attachmentMenuOpen}
            coreModelSupportsVision={coreModelSupportsVision}
            onToggle={onToggleAttachmentMenu}
            onPickImage={onPickImage}
            onPickFile={onPickFile}
            disabled={feedbackMode || answeringAsk || attachmentsDisabled}
          />
          <div className="relative">
            <SessionSafetyControl sessionId={sessionId} />
          </div>
          <ContextUsageRing
            sessionId={sessionId}
            configuredWindowSize={coreModelContextWindow}
          />
          <ComposerReasoningControl
            value={reasoningPreference}
            onChange={onReasoningPreferenceChange}
            disabled={feedbackMode || answeringAsk || effectiveWaitingForReply}
          />
        </div>
        <div data-testid="chat-composer-primary-action">
          <button
            type="button"
            onClick={onPrimaryAction}
            disabled={
              sendingMessage
              || stoppingReply
              || (choiceOnlyAsk && !validChoiceSelected)
            }
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-[0_8px_18px_hsl(var(--primary)/0.14)] transition-[background-color,box-shadow,color] duration-200 hover:bg-[hsl(var(--primary)/0.92)] hover:shadow-[0_10px_22px_hsl(var(--primary)/0.18)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-[hsl(var(--muted))] disabled:text-muted-foreground disabled:shadow-none"
            aria-label={feedbackMode
              ? t('chat.recallFeedback.send')
              : effectiveWaitingForReply ? t('chat.stop') : t('chat.send')}
            title={feedbackMode
              ? t('chat.recallFeedback.send')
              : effectiveWaitingForReply ? t('chat.stop') : t('chat.send')}
          >
            {sendingMessage || stoppingReply ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : effectiveWaitingForReply ? (
              <span aria-hidden="true" className="h-3.5 w-3.5 rounded-[2px] bg-current" />
            ) : (
              <ArrowUp className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
