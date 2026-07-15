import { RotateCcw, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { RecallFeedbackDraft } from '@/domain/chat/recall-feedback';

type ComposerRecallFeedbackBannerProps = {
  draft: RecallFeedbackDraft;
  onConvertToNormal: () => void;
  onCancel: () => void;
};

export const ComposerRecallFeedbackBanner = ({
  draft,
  onConvertToNormal,
  onCancel,
}: ComposerRecallFeedbackBannerProps) => {
  const { t } = useTranslation('app');
  const detail = draft.kind === 'item_irrelevant'
    ? draft.findingLabel
    : t('chat.recallFeedback.answerScope');

  return (
    <div
      className="mx-3 mt-3 flex items-center gap-2 rounded-lg border border-primary/15 bg-primary/[0.045] px-3 py-2 text-xs"
      data-testid="recall-feedback-banner"
    >
      <RotateCcw className="h-3.5 w-3.5 shrink-0 text-primary/75" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-foreground/85">{t('chat.recallFeedback.draftLabel')}</div>
        {detail ? (
          <div className="truncate pt-0.5 text-[11px] text-muted-foreground/75">{detail}</div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onConvertToNormal}
        className="shrink-0 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t('chat.recallFeedback.convertToNormal')}
      </button>
      <button
        type="button"
        onClick={onCancel}
        aria-label={t('chat.recallFeedback.cancel')}
        title={t('chat.recallFeedback.cancel')}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
};
