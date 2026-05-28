import { useTranslation } from 'react-i18next';
import { useAvailability } from '../../hooks/useAvailability';
import { EmptyStateSensorCard } from '../empty-state/EmptyStateSensorCard';
import { getEmptyStatePluginMeta } from '../../constants/emptyStatePriorities';
import type { SuggestionProposal } from '../../api/modules/systemSuggestions';

export interface SystemSuggestionSideCardProps {
  proposal: SuggestionProposal;
  onClose: () => void;
  onDecline: (dedupeKey: string) => void;
  onActivated: (pluginId: string) => void;
}

export function SystemSuggestionSideCard({
  proposal,
  onClose,
  onDecline,
  onActivated,
}: SystemSuggestionSideCardProps): JSX.Element {
  const { t, i18n } = useTranslation('onboarding');
  const { entries } = useAvailability(proposal.plugin_ids);
  const locale = i18n.language === 'zh-CN' || i18n.language === 'zh' ? 'zh' : 'en';
  const rationale = proposal.rationale[locale] ?? proposal.rationale.en;
  const installable = entries.filter((e) => e.available);

  return (
    <aside
      className="fixed right-4 top-20 z-40 w-80 rounded-lg border border-[#e6d7c5] bg-white p-4 shadow-xl dark:border-[#5b4a3d] dark:bg-[#2a2018]"
      role="complementary"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-[#35261f] dark:text-[#f4eadf]">
          {t('systemSuggestion.fallbackHeading')}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('systemSuggestion.dismiss')}
          className="text-[#7d685a] hover:text-[#35261f] dark:text-[#c8b7a7] dark:hover:text-[#f4eadf]"
        >
          ×
        </button>
      </div>
      <p className="mt-2 text-xs text-[#7d685a] dark:text-[#c8b7a7]">{rationale}</p>

      <div className="mt-3 space-y-2">
        {installable.map((entry) => {
          const meta = getEmptyStatePluginMeta(entry.plugin_id);
          // Safe fallback when plugin isn't in Plan 3's priority list — use
          // plain plugin_id as title and connect copy as value.
          const titleKey = meta?.titleKey ?? 'emptyState.connect';
          const valueKey = meta?.valueKey ?? 'emptyState.connect';
          return (
            <div data-testid="system-suggestion-side-card-row" key={entry.plugin_id}>
              <EmptyStateSensorCard
                pluginId={entry.plugin_id}
                titleKey={titleKey}
                valueKey={valueKey}
                iconId={meta?.iconId}
                onConnect={(pluginId) => onActivated(pluginId)}
              />
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => onDecline(proposal.dedupe_key)}
          className="rounded-md border border-[#d8c9b8] px-3 py-1.5 text-xs text-[#35261f] dark:border-[#7d685a] dark:text-[#f4eadf]"
        >
          {t('systemSuggestion.decline')}
        </button>
      </div>
    </aside>
  );
}
