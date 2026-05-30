import { useTranslation } from 'react-i18next';
import type { SuggestionProposal } from '../../api/modules/systemSuggestions';

export interface SystemSuggestionTopBarProps {
  proposal: SuggestionProposal | null;
  onOpen: (proposal: SuggestionProposal) => void;
  onDismiss: (dedupeKey: string, kind: 'transient' | 'explicit' | 'never') => void;
}

export function SystemSuggestionTopBar({
  proposal,
  onOpen,
  onDismiss,
}: SystemSuggestionTopBarProps): JSX.Element | null {
  const { t, i18n } = useTranslation('onboarding');
  if (!proposal) return null;
  const locale = i18n.language === 'zh-CN' || i18n.language === 'zh' ? 'zh' : 'en';
  const rationale = proposal.rationale[locale] ?? proposal.rationale.en;

  return (
    <div className="px-2 pt-2">
      <div className="flex items-center gap-2.5 rounded-lg border border-border/55 bg-card px-4 py-2.5 text-sm text-foreground shadow-sm">
        <span aria-hidden className="text-base leading-none text-primary">💡</span>
        <button
          type="button"
          onClick={() => onOpen(proposal)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left transition hover:opacity-80"
        >
          <span className="min-w-0 flex-1 truncate">{rationale}</span>
          <span aria-hidden className="shrink-0 text-muted-foreground">→</span>
        </button>
        <button
          type="button"
          onClick={() => onDismiss(proposal.dedupe_key, 'transient')}
          className="shrink-0 rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
          aria-label={t('systemSuggestion.dismiss')}
        >
          ×
        </button>
      </div>
    </div>
  );
}
