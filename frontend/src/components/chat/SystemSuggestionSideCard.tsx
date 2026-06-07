import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePluginActivation } from '../../hooks/usePluginActivation';
import { PluginActivationDialog } from '../plugins/PluginActivationDialog';
import type { SuggestionProposal } from '../../api/modules/systemSuggestions';

/** "netease-music" → "Netease Music" — readable fallback when a plugin has no
 *  localized name in the `pluginNames` i18n map. */
function humanizePluginId(pluginId: string): string {
  return pluginId
    .split(/[-_]/)
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

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
  const locale = i18n.language === 'zh-CN' || i18n.language === 'zh' ? 'zh' : 'en';
  const rationale = proposal.rationale[locale] ?? proposal.rationale.en;

  // The backend already filtered the proposal's plugins by availability, so we
  // render a row for each plugin directly (no client-side availability re-probe
  // — that probe only resolves *installed* plugins and would wrongly hide
  // not-yet-installed suggestions). `activated` hides a row after success.
  const [activated, setActivated] = useState<Set<string>>(new Set());
  const visiblePluginIds = proposal.plugin_ids.filter((pid) => !activated.has(pid));

  const { dialogState, installingPluginId, openDialog, closeDialog, confirm } = usePluginActivation({
    onSuccess: (pluginId) => {
      onActivated(pluginId);
      setActivated((prev) => new Set(prev).add(pluginId));
    },
  });

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
        {visiblePluginIds.map((pluginId) => {
          // Name the plugin so the user knows *what* they're enabling (the old
          // generic "启用 / 启用" said nothing). Localized via `pluginNames`,
          // humanized id as fallback.
          const name = t(`pluginNames.${pluginId}`, { defaultValue: humanizePluginId(pluginId) });
          const needsInstall = proposal.installable_plugin_ids.includes(pluginId);
          const isInstalling = installingPluginId === pluginId;
          const label = isInstalling
            ? t('emptyState.installing')
            : needsInstall
              ? t('emptyState.installAndConnect')
              : t('emptyState.connect');
          return (
            <div
              data-testid="system-suggestion-side-card-row"
              key={pluginId}
              className="flex items-center gap-3"
            >
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                {name}
              </span>
              <button
                type="button"
                data-testid={`empty-state-connect-${pluginId}`}
                onClick={() => { void openDialog(pluginId, { install: needsInstall }); }}
                disabled={isInstalling}
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

      {dialogState && (
        <PluginActivationDialog
          open
          onClose={closeDialog}
          flow={dialogState.flow}
          initialValues={{}}
          onConfirm={confirm}
          pluginId={dialogState.pluginId}
        />
      )}
    </aside>
  );
}
