import { useTranslation } from 'react-i18next';
import type {
  DismissalKind,
  SuggestionProposal,
} from '../../api/modules/systemSuggestions';

export interface SystemSuggestionTopBarProps {
  proposal: SuggestionProposal | null;
  onOpen: (proposal: SuggestionProposal) => void;
  onDismiss: (dedupeKey: string, kind: DismissalKind) => void;
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
    <div className="flex items-center justify-between gap-2 border-b border-[#e6d7c5] bg-[#fbf6ef] px-4 py-1.5 text-xs dark:border-[#5b4a3d] dark:bg-[#3d2f25]">
      <button
        type="button"
        onClick={() => onOpen(proposal)}
        className="flex flex-1 items-center gap-2 text-left text-[#35261f] hover:underline dark:text-[#f4eadf]"
      >
        <span>💡</span>
        <span>{rationale}</span>
        <span className="ml-1">→</span>
      </button>
      <button
        type="button"
        onClick={() => onDismiss(proposal.dedupe_key, 'transient')}
        aria-label={t('systemSuggestion.dismiss')}
        className="text-[#7d685a] hover:text-[#35261f] dark:text-[#c8b7a7] dark:hover:text-[#f4eadf]"
      >
        ×
      </button>
    </div>
  );
}
