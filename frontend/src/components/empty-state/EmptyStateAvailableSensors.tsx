import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { useInstallableSensors } from '../../hooks/useInstallableSensors';
import { usePluginActivation } from '../../hooks/usePluginActivation';
import {
  EMPTY_STATE_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
} from '../../constants/emptyStatePriorities';
import type { InstallableItem } from '../../api/modules/systemSuggestions';
import { EmptyStateSensorCard } from './EmptyStateSensorCard';
import { PluginActivationDialog } from '../plugins/PluginActivationDialog';

/**
 * Orchestrator component for the empty-state CTA grid.
 *
 * Responsibilities:
 *   1. Source the candidate plugins from the backend
 *      `GET /system-suggestions/installable` endpoint via
 *      `useInstallableSensors`. The backend returns the availability-filtered
 *      union of locally-installed sensors and registry-available plugins, each
 *      tagged with an `installed` flag.
 *   2. Render an `<EmptyStateSensorCard>` for each item that has empty-state
 *      display metadata, sorted by `EMPTY_STATE_PRIORITY_PLUGINS`. Items
 *      without metadata are silently skipped.
 *   3. On a Connect click, open `<PluginActivationDialog>` via
 *      `usePluginActivation`. For registry-only items (`installed === false`)
 *      we pass `{ install: true }` so the plugin is downloaded from the
 *      registry before the activation flow runs (install-then-activate).
 *   4. Persist activation through the same path Settings uses (handled by
 *      `usePluginActivation`):
 *        - `sensorsApi.requestAuthorization` when the flow has
 *          `authorize_on_confirm`
 *        - `pluginsApi.updateSettings` with the user-supplied field values,
 *          plus `enabled_key=true` and `configured_key=true` from the flow.
 *
 * The orchestrator is intentionally self-contained: unlike
 * `TimelineSourcesSection` it does NOT lift draft state up to a parent. The
 * empty-state surface persists immediately on confirm and then refreshes the
 * installable list so the connected card disappears from the grid on success.
 */

export interface EmptyStateAvailableSensorsProps {
  /**
   * Plugin IDs that are already installed/configured and should be hidden from
   * the grid. The orchestrator filters them from the rendered cards.
   */
  excludePluginIds?: string[];
  /** Optional callback fired after a plugin is successfully activated. */
  onActivated?: (pluginId: string) => void;
}

/**
 * Stable index for the priority ordering. Plugins absent from the priority
 * list sort after every listed plugin (and keep their relative input order via
 * a stable sort).
 */
function priorityIndex(pluginId: string): number {
  const idx = (EMPTY_STATE_PRIORITY_PLUGINS as readonly string[]).indexOf(pluginId);
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

export function EmptyStateAvailableSensors({
  excludePluginIds,
  onActivated,
}: EmptyStateAvailableSensorsProps): JSX.Element | null {
  const { t } = useTranslation('onboarding');

  const { items, loading, refresh } = useInstallableSensors();

  const { dialogState, openDialog, closeDialog, confirm } = usePluginActivation({
    onSuccess: async (pluginId) => {
      await refresh();
      onActivated?.(pluginId);
    },
  });

  const excluded = useMemo(
    () => new Set(excludePluginIds ?? []),
    [excludePluginIds],
  );

  // Filter out excluded plugins, then order by the empty-state priority list
  // (plugins not in the list go last, stable).
  const ordered = useMemo<InstallableItem[]>(() => {
    const visible = items.filter((item) => !excluded.has(item.plugin_id));
    return [...visible].sort(
      (a, b) => priorityIndex(a.plugin_id) - priorityIndex(b.plugin_id),
    );
  }, [items, excluded]);

  if (loading) {
    // Suppress flash-of-cards while the installable list is in flight. The hook
    // flips loading=false once items are populated.
    return null;
  }
  if (ordered.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-[#35261f] dark:text-[#f4eadf]">
        {t('emptyState.heading')}
      </h3>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {ordered.map((item) => {
          const meta = getEmptyStatePluginMeta(item.plugin_id);
          if (!meta) {
            return null;
          }
          return (
            <EmptyStateSensorCard
              key={item.plugin_id}
              pluginId={item.plugin_id}
              titleKey={meta.titleKey}
              valueKey={meta.valueKey}
              iconId={meta.iconId}
              connectLabelKey={
                item.installed
                  ? 'emptyState.connect'
                  : 'emptyState.installAndConnect'
              }
              onConnect={(pluginId) => {
                // Install-first for registry-only items: download from the
                // registry before opening the activation flow.
                void openDialog(pluginId, { install: !item.installed });
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
