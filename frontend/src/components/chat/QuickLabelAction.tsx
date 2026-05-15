import type { RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

type QuickLabelActionProps = {
  isOpen: boolean;
  draft: string;
  popoverRef: RefObject<HTMLDivElement>;
  position?: {
    x: number;
    y: number;
  } | null;
  emojiOptions: string[];
  onToggle: (event: React.MouseEvent<HTMLButtonElement>) => void;
  onEmojiSelect: (emoji: string) => void;
  onDraftChange: (value: string) => void;
  onDraftCompositionStart: () => void;
  onDraftCompositionEnd: (value: string) => void;
  onApplyDraft: () => void;
};

export const QuickLabelAction = ({
  isOpen,
  draft,
  popoverRef,
  position,
  emojiOptions,
  onToggle,
  onEmojiSelect,
  onDraftChange,
  onDraftCompositionStart,
  onDraftCompositionEnd,
  onApplyDraft,
}: QuickLabelActionProps) => {
  const { t } = useTranslation();

  return (
    <div data-testid="chat-label-action-wrap" className="relative flex items-center">
      <button
        type="button"
        aria-label={t('chat.label.action')}
        title={t('chat.label.action')}
        onClick={onToggle}
        className="inline-flex items-center text-[11px] font-medium text-muted-foreground/55 transition-colors hover:text-muted-foreground"
      >
        {t('chat.label.action')}
      </button>
      {isOpen ? (
        <div
          ref={popoverRef}
          data-testid="chat-label-popover"
          className="fixed z-[95] w-[21rem] rounded-2xl border border-border/70 bg-background/95 p-3 shadow-[0_18px_40px_rgba(15,23,42,0.14)] backdrop-blur"
          style={{
            left: position?.x ?? 16,
            top: position?.y ?? 16,
          }}
        >
          <div className="grid grid-cols-5 gap-2">
            {emojiOptions.map((emoji) => (
              <button
                key={emoji}
                type="button"
                aria-label={emoji}
                className="flex h-11 items-center justify-center rounded-xl border border-border/50 bg-muted/35 text-2xl transition-colors hover:border-primary/30 hover:bg-muted/60"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onEmojiSelect(emoji);
                }}
              >
                {emoji}
              </button>
            ))}
          </div>
          <div className="mt-3 border-t border-border/60 pt-3">
            <p className="mb-2 text-xs text-muted-foreground">{t('chat.label.customHint')}</p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={draft}
                placeholder={t('chat.label.customPlaceholder')}
                onChange={(event) => onDraftChange(event.target.value)}
                onCompositionStart={onDraftCompositionStart}
                onCompositionEnd={(event) => onDraftCompositionEnd(event.currentTarget.value)}
                className="h-10 flex-1 rounded-xl border border-border/60 bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-primary/45"
              />
              <Button
                type="button"
                size="sm"
                disabled={!draft.trim()}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onApplyDraft();
                }}
              >
                {t('chat.label.send')}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};