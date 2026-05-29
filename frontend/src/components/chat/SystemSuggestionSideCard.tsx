import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAvailability } from '../../hooks/useAvailability';
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
  const { entries, refresh } = useAvailability(proposal.plugin_ids);
  const locale = i18n.language === 'zh-CN' || i18n.language === 'zh' ? 'zh' : 'en';
  const rationale = proposal.rationale[locale] ?? proposal.rationale.en;

  const [activated, setActivated] = useState<Set<string>>(new Set());
  const installable = entries.filter((e) => e.available && !activated.has(e.plugin_id));

  const { dialogState, openDialog, closeDialog, confirm } = usePluginActivation({
    onSuccess: async (pluginId) => {
      await refresh();
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
        {installable.map((entry) => {
          const meta = getEmptyStatePluginMeta(entry.plugin_id);
          // Safe fallback when plugin isn't in Plan 3's priority list — use
          // plain plugin_id as title and connect copy as value.
          const titleKey = meta?.titleKey ?? 'emptyState.connect';
          const valueKey = meta?.valueKey ?? 'emptyState.connect';
          // Plugins listed in installable_plugin_ids are not yet installed
          // locally — take the install-first branch (download from registry,
          // then open the activation dialog). Already-installed plugins
          // activate directly.
          const needsInstall = proposal.installable_plugin_ids.includes(entry.plugin_id);
          return (
            <div data-testid="system-suggestion-side-card-row" key={entry.plugin_id}>
              <EmptyStateSensorCard
                pluginId={entry.plugin_id}
                titleKey={titleKey}
                valueKey={valueKey}
                iconId={meta?.iconId}
                connectLabelKey={needsInstall ? 'emptyState.installAndConnect' : 'emptyState.connect'}
                onConnect={(pluginId) => { void openDialog(pluginId, { install: needsInstall }); }}
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
