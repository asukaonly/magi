import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePluginActivation } from '../../hooks/usePluginActivation';
import { EmptyStateSensorCard } from '../empty-state/EmptyStateSensorCard';
import { PluginActivationDialog } from '../plugins/PluginActivationDialog';
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
  const locale = i18n.language === 'zh-CN' || i18n.language === 'zh' ? 'zh' : 'en';
  const rationale = proposal.rationale[locale] ?? proposal.rationale.en;

  // The backend already filtered the proposal's plugins by availability, so we
  // render a row for each plugin directly (no client-side availability re-probe
  // — that probe only resolves *installed* plugins and would wrongly hide
  // not-yet-installed suggestions). `activated` hides a row after success.
  const [activated, setActivated] = useState<Set<string>>(new Set());
  const visiblePluginIds = proposal.plugin_ids.filter((pid) => !activated.has(pid));

  const { dialogState, openDialog, closeDialog, confirm } = usePluginActivation({
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
          const meta = getEmptyStatePluginMeta(pluginId);
          const titleKey = meta?.titleKey ?? 'emptyState.connect';
          const valueKey = meta?.valueKey ?? 'emptyState.connect';
          const needsInstall = proposal.installable_plugin_ids.includes(pluginId);
          return (
            <div data-testid="system-suggestion-side-card-row" key={pluginId}>
              <EmptyStateSensorCard
                pluginId={pluginId}
                titleKey={titleKey}
                valueKey={valueKey}
                iconId={meta?.iconId}
                connectLabelKey={needsInstall ? 'emptyState.installAndConnect' : 'emptyState.connect'}
                onConnect={(pid) => { void openDialog(pid, { install: needsInstall }); }}
              />
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
