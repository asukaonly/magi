import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { useAvailability } from '../../hooks/useAvailability';
import { usePluginActivation } from '../../hooks/usePluginActivation';
import {
  EMPTY_STATE_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
} from '../../constants/emptyStatePriorities';
import { EmptyStateSensorCard } from './EmptyStateSensorCard';
import { PluginActivationDialog } from '../plugins/PluginActivationDialog';

/**
 * Orchestrator component for the Plan 3 empty-state CTA grid.
 *
 * Responsibilities:
 *   1. Probe availability for the Plan 3 priority plugin list via
 *      `useAvailability`.
 *   2. Render an `<EmptyStateSensorCard>` for each plugin whose probe came back
 *      `available: true`. Unavailable plugins (missing OS, wrong platform,
 *      not-installed app, etc.) are silently skipped — the empty state is
 *      *aspirational but actionable*.
 *   3. On a Connect click, lazily fetch the sensor status list, locate the
 *      matching source for the plugin, and open `<PluginActivationDialog>`
 *      with the source's `activation_flow` spec.
 *   4. Persist activation through the same path Settings uses:
 *        - `sensorsApi.requestAuthorization` when the flow has
 *          `authorize_on_confirm`
 *        - `pluginsApi.updateSettings` with the user-supplied field values,
 *          plus `enabled_key=true` and `configured_key=true` from the flow.
 *
 * The orchestrator is intentionally self-contained: unlike
 * `TimelineSourcesSection` it does NOT lift draft state up to a parent. The
 * empty-state surface persists immediately on confirm and then refreshes
 * availability so the connected card disappears from the grid on success.
 */

export interface EmptyStateAvailableSensorsProps {
  /**
   * Plugin IDs that are already installed/configured and should be hidden from
   * the grid. The orchestrator both filters them from the `useAvailability`
   * probe (so we don't waste a check) and from the rendered cards.
   */
  excludePluginIds?: string[];
  /** Optional callback fired after a plugin is successfully activated. */
  onActivated?: (pluginId: string) => void;
}

export function EmptyStateAvailableSensors({
  excludePluginIds,
  onActivated,
}: EmptyStateAvailableSensorsProps): JSX.Element | null {
  const { t } = useTranslation('onboarding');

  // Filter the priority list *before* it reaches useAvailability so the
  // backend probe only checks plugins we actually intend to surface.
  const priorityList = useMemo<string[]>(
    () =>
      EMPTY_STATE_PRIORITY_PLUGINS.filter(
        (id) => !(excludePluginIds ?? []).includes(id),
      ),
    [excludePluginIds],
  );

  const { entries, loading, refresh } = useAvailability(priorityList);

  const { dialogState, openDialog, closeDialog, confirm } = usePluginActivation({
    onSuccess: async (pluginId) => {
      await refresh();
      onActivated?.(pluginId);
    },
  });

  // Defence-in-depth: the prior filter trims the probe input, but the
  // resolved entries may still include excluded IDs if the hook's backend
  // ignores the requested subset. Re-apply the exclusion before rendering.
  const excluded = useMemo(
    () => new Set(excludePluginIds ?? []),
    [excludePluginIds],
  );

  const installable = useMemo(
    () => entries.filter((entry) => entry.available && !excluded.has(entry.plugin_id)),
    [entries, excluded],
  );

  if (loading) {
    // Suppress flash-of-cards while the probe is in flight. The hook flips
    // loading=false once entries are populated.
    return null;
  }
  if (installable.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-[#35261f] dark:text-[#f4eadf]">
        {t('emptyState.heading')}
      </h3>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {installable.map((entry) => {
          const meta = getEmptyStatePluginMeta(entry.plugin_id);
          if (!meta) {
            return null;
          }
          return (
            <EmptyStateSensorCard
              key={entry.plugin_id}
              pluginId={entry.plugin_id}
              titleKey={meta.titleKey}
              valueKey={meta.valueKey}
              iconId={meta.iconId}
              onConnect={(pluginId) => {
                void openDialog(pluginId);
              }}
            />
          );
        })}
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
    </div>
  );
}

export default EmptyStateAvailableSensors;
