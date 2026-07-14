import { useTranslation } from 'react-i18next';
import { usePluginInstallPanelStore } from '../../stores/pluginInstallPanel';
import type { SuggestionProposal } from '../../api/modules/systemSuggestions';
import { PluginIcon } from '../plugins/PluginIcon';
import { localizedPluginText } from '../../utils/plugin-display-groups';

export interface SystemSuggestionSideCardProps {
  proposal: SuggestionProposal;
  onClose: () => void;
  onDecline: (dedupeKey: string) => void;
  /**
   * Optional. Kept for call-site compatibility, but no longer fired from here:
   * connect now opens the shared <PluginInstallPanel>, which owns the connect
   * flow and its own done state, so the side-card never learns of success.
   */
  onActivated?: (pluginId: string) => void;
}

export function SystemSuggestionSideCard({
  proposal,
  onClose,
  onDecline,
}: SystemSuggestionSideCardProps): JSX.Element {
  const { t, i18n } = useTranslation('onboarding');
  const locale = i18n.language === 'zh-CN' || i18n.language === 'zh' ? 'zh' : 'en';
  const rationale = proposal.rationale[locale] ?? proposal.rationale.en;

  // The backend already filtered the proposal's plugins by availability, so we
  // render a row for each plugin directly (no client-side availability re-probe
  // — that probe only resolves *installed* plugins and would wrongly hide
  // not-yet-installed suggestions).
  // Connect opens the single MainLayout-mounted <PluginInstallPanel>, which owns
  // the full honest flow (install → enable → sync → build-memory).
  const openPanel = usePluginInstallPanelStore((s) => s.openPanel);

  return (
    <aside
      className="fixed right-4 top-20 z-40 w-80 rounded-lg border border-border/55 bg-card p-4 shadow-xl"
      role="complementary"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">
          {t('systemSuggestion.fallbackHeading')}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={t('systemSuggestion.dismiss')}
          className="text-muted-foreground hover:text-foreground"
        >
          ×
        </button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{rationale}</p>

      <div className="mt-3 space-y-2">
        {proposal.plugins.map((plugin) => {
          const name = localizedPluginText(plugin.name, plugin.name_i18n, i18n.language);
          const needsInstall = !plugin.installed;
          const label = needsInstall
            ? t('emptyState.installAndConnect')
            : t('emptyState.connect');
          return (
            <div
              data-testid="system-suggestion-side-card-row"
              key={plugin.plugin_id}
              className="flex items-center gap-3"
            >
              <PluginIcon iconId={plugin.icon} className="h-5 w-5 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                {name}
              </span>
              <button
                type="button"
                data-testid={`empty-state-connect-${plugin.plugin_id}`}
                onClick={() =>
                  openPanel(plugin.plugin_id, {
                    install: needsInstall,
                    pluginName: name,
                    pluginIcon: plugin.icon,
                  })
                }
                className="ml-auto shrink-0 min-w-[5.5rem] rounded-md border border-primary/40 px-3 py-1.5 text-center text-xs font-medium text-primary transition hover:bg-primary/10 disabled:opacity-50"
              >
                {label}
              </button>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={() => onDecline(proposal.dedupe_key)}
          className="rounded-md border border-border/55 px-3 py-1.5 text-xs text-foreground"
        >
          {t('systemSuggestion.decline')}
        </button>
      </div>
    </aside>
  );
}
