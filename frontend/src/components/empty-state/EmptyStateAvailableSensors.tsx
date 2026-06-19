import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { useInstallableSensors } from '../../hooks/useInstallableSensors';
import { usePluginInstallPanelStore } from '../../stores/pluginInstallPanel';
import { useChatShellStore } from '../../stores/chat-shell';
import {
  EMPTY_STATE_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
  type EmptyStatePluginMeta,
} from '../../constants/emptyStatePriorities';
import type { InstallableItem } from '../../api/modules/systemSuggestions';
import { EmptyStateSensorCard } from './EmptyStateSensorCard';

/**
 * Orchestrator component for the empty-state CTA list.
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
 *   3. On a Connect click, open the single MainLayout-mounted
 *      `<PluginInstallPanel>` via `usePluginInstallPanelStore.openPanel`. For
 *      registry-only items (`installed === false`) we pass `{ install: true }`
 *      so the panel downloads the plugin from the registry before the connect
 *      flow runs (install-then-connect). The panel owns the full honest flow
 *      (install → enable → sync → build-memory) and its own done state.
 *
 * The orchestrator is intentionally self-contained: unlike
 * `TimelineSourcesSection` it does NOT lift draft state up to a parent, and it
 * no longer renders its own dialog — the shared panel handles every entry
 * point.
 */

export interface EmptyStateAvailableSensorsProps {
  /**
   * Plugin IDs that are already installed/configured and should be hidden from
   * the list. The orchestrator filters them from the rendered rows.
   */
  excludePluginIds?: string[];
  i18nNamespace?: string;
  i18nKeyPrefix?: string;
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

/**
 * Hard cap on how many cards the empty-state list renders. Items beyond the
 * top-N (by priority, after dropping metadata-less ones) stay behind the
 * "Browse all plugins" marketplace exit rather than growing the list.
 */
const MAX_EMPTY_STATE_CARDS = 5;

export function EmptyStateAvailableSensors({
  excludePluginIds,
  i18nNamespace = 'onboarding',
  i18nKeyPrefix,
}: EmptyStateAvailableSensorsProps): JSX.Element | null {
  const { t } = useTranslation(i18nNamespace);
  const keyed = (key: string) => (i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key);

  const { items, loading } = useInstallableSensors();

  // Connect now opens the single MainLayout-mounted <PluginInstallPanel>, which
  // owns the full honest flow (install → enable → sync → build-memory) and its
  // own done state. This component no longer renders its own dialog.
  const openPanel = usePluginInstallPanelStore((s) => s.openPanel);

  // "Browse all plugins" footer deep-links into Settings → plugin marketplace,
  // the full catalog beyond the META-whitelisted empty-state cards. Same intent
  // mechanism ScheduleConfigPage uses to jump into a settings section.
  const setActivePanel = useChatShellStore((s) => s.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore(
    (s) => s.setSettingsNavigationIntent,
  );

  const excluded = useMemo(
    () => new Set(excludePluginIds ?? []),
    [excludePluginIds],
  );

  // Filter out excluded plugins, order by the empty-state priority list (plugins
  // not in the list go last, stable), drop items without display metadata, then
  // cap to the top MAX_EMPTY_STATE_CARDS — the remainder stays behind the
  // marketplace exit so the empty state never grows unbounded.
  const visible = useMemo<{ item: InstallableItem; meta: EmptyStatePluginMeta }[]>(() => {
    const candidates = items.filter((item) => !excluded.has(item.plugin_id));
    const sorted = [...candidates].sort(
      (a, b) => priorityIndex(a.plugin_id) - priorityIndex(b.plugin_id),
    );
    const withMeta: { item: InstallableItem; meta: EmptyStatePluginMeta }[] = [];
    for (const item of sorted) {
      const meta = getEmptyStatePluginMeta(item.plugin_id);
      if (meta) {
        withMeta.push({ item, meta });
      }
    }
    return withMeta.slice(0, MAX_EMPTY_STATE_CARDS);
  }, [items, excluded]);

  if (loading) {
    // Suppress flash-of-cards while the installable list is in flight. The hook
    // flips loading=false once items are populated.
    return null;
  }

  // "Browse all plugins" always-available exit into the full marketplace —
  // rendered even when no cards are available on this device, so the user is
  // never left without a way in.
  const browseAll = (
    <button
      type="button"
      data-testid="empty-state-browse-all"
      onClick={() => {
        setSettingsNavigationIntent({ section: 'pluginsMarketplace' });
        setActivePanel('settings');
      }}
      className="text-xs font-semibold text-muted-foreground transition hover:text-foreground"
    >
      {t(keyed('emptyState.browseAll'))}
    </button>
  );

  if (visible.length === 0) {
    // No device-available, whitelisted cards — still surface the marketplace
    // exit rather than rendering nothing.
    return <div className="text-left">{browseAll}</div>;
  }

  return (
    // text-left: the timeline/memory empty states wrap this in a `text-center`
    // container; without this the inherited centering shifts each row's (short)
    // title vs (longer) description so they look misaligned.
    <div className="space-y-3 text-left">
      <h3 className="text-sm font-medium text-foreground">
        {t(keyed('emptyState.heading'))}
      </h3>
      <div className="divide-y divide-border/35 overflow-hidden rounded-lg bg-[hsl(var(--app-chrome-elevated)/0.44)] shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)]">
        {visible.map(({ item, meta }) => (
          <EmptyStateSensorCard
            key={item.plugin_id}
            pluginId={item.plugin_id}
            titleKey={meta.titleKey}
            valueKey={meta.valueKey}
            iconId={meta.iconId}
            i18nNamespace={i18nNamespace}
            i18nKeyPrefix={i18nKeyPrefix}
            connectLabelKey={
              item.installed ? 'emptyState.connect' : 'emptyState.installAndConnect'
            }
            onConnect={(pluginId) => {
              // Install-first for registry-only items: the panel downloads
              // from the registry before the connect flow runs.
              openPanel(pluginId, { install: !item.installed });
            }}
          />
        ))}
      </div>
      {browseAll}
    </div>
  );
}

export default EmptyStateAvailableSensors;
