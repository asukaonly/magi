import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { useInstallableSensors } from '../../hooks/useInstallableSensors';
import {
  usePluginInstallPanelStore,
  type PluginInstallPanelContext,
} from '../../stores/pluginInstallPanel';
import { useChatShellStore } from '../../stores/chat-shell';
import {
  BROWSER_HISTORY_PRIORITY_PLUGINS,
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
 *   2. Render an `<EmptyStateSensorCard>` for each first-context item that has
 *      display metadata, sorted by `EMPTY_STATE_PRIORITY_PLUGINS`. Browser
 *      history plugins share one top slot; items outside the first-context list
 *      are silently skipped even when they have generic suggestion metadata.
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
  /**
   * Embedded surfaces outside the main app shell can hide the marketplace
   * deep-link and keep only direct connection entry points.
   */
  showBrowseAll?: boolean;
  /**
   * Optional conservative fallback cards for surfaces that must not collapse to
   * empty when the installable suggestion endpoint is unavailable.
   */
  fallbackPluginIds?: string[];
  /**
   * When the backend only returns a sparse installable list, embedded first-run
   * surfaces can still fill the remaining top slots with conservative fallback
   * cards so the page does not look artificially limited.
   */
  fillWithFallback?: boolean;
  /**
   * Optional preloaded suggestions. Onboarding uses this to avoid a blank
   * completion page while the same suggestions are already being fetched.
   */
  installableItems?: InstallableItem[];
  installableLoading?: boolean;
  /**
   * Called after the shared plugin panel opens. First-run surfaces use this to
   * track that the real install/connect flow started.
   */
  onConnectStart?: (pluginId: string, options: { install: boolean }) => void;
  /**
   * Called after the shared plugin panel finishes a successful connect flow.
   * First-run surfaces use this to dismiss guidance only after a source is
   * actually connected.
   */
  onConnectDone?: (pluginId: string) => void;
  /**
   * Lets embedded first-run surfaces request a lighter connect flow without
   * changing Settings or normal plugin-entry behavior.
   */
  panelContext?: PluginInstallPanelContext;
}

/**
 * Stable index for the priority ordering. Plugins absent from the priority
 * list sort after every listed plugin (and keep their relative input order via
 * a stable sort).
 */
function priorityIndex(pluginId: string): number {
  if ((BROWSER_HISTORY_PRIORITY_PLUGINS as readonly string[]).includes(pluginId)) {
    return 0;
  }
  const idx = (EMPTY_STATE_PRIORITY_PLUGINS as readonly string[]).indexOf(pluginId);
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

function browserHistoryIndex(pluginId: string): number {
  const idx = (BROWSER_HISTORY_PRIORITY_PLUGINS as readonly string[]).indexOf(pluginId);
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

function isBrowserHistoryPlugin(pluginId: string): boolean {
  return browserHistoryIndex(pluginId) !== Number.MAX_SAFE_INTEGER;
}

function isFirstContextPlugin(pluginId: string): boolean {
  return priorityIndex(pluginId) !== Number.MAX_SAFE_INTEGER;
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
  showBrowseAll = true,
  fallbackPluginIds,
  fillWithFallback = false,
  installableItems,
  installableLoading,
  onConnectStart,
  onConnectDone,
  panelContext = 'default',
}: EmptyStateAvailableSensorsProps): JSX.Element | null {
  const { t } = useTranslation(i18nNamespace);
  const keyed = (key: string) => (i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key);

  const hookState = useInstallableSensors();
  const items = installableItems ?? hookState.items ?? [];
  const loading = installableLoading ?? hookState.loading;

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
    const collectWithMeta = (sourceItems: InstallableItem[]) => {
      const browserHistory = [...sourceItems]
        .filter((item) => isBrowserHistoryPlugin(item.plugin_id))
        .sort((a, b) => browserHistoryIndex(a.plugin_id) - browserHistoryIndex(b.plugin_id))
        .slice(0, 1);
      const otherItems = sourceItems.filter((item) => !isBrowserHistoryPlugin(item.plugin_id));
      const sorted = [...browserHistory, ...otherItems].sort(
        (a, b) => priorityIndex(a.plugin_id) - priorityIndex(b.plugin_id),
      );
      const withMeta: { item: InstallableItem; meta: EmptyStatePluginMeta }[] = [];
      for (const item of sorted) {
        const meta = getEmptyStatePluginMeta(item.plugin_id);
        if (meta && isFirstContextPlugin(item.plugin_id)) {
          withMeta.push({ item, meta });
        }
      }
      return withMeta;
    };

    const fallbackItems = (fallbackPluginIds ?? [])
      .filter((pluginId) => !excluded.has(pluginId))
      .map((pluginId) => ({
        plugin_id: pluginId,
        category: 'onboarding_fallback',
        installed: false,
        rationale: { zh: '', en: '' },
      }));

    const candidates = items.filter((item) => !excluded.has(item.plugin_id));
    const candidatesHaveBrowserHistory = candidates.some((item) =>
      isBrowserHistoryPlugin(item.plugin_id),
    );
    const mergedCandidates = fillWithFallback
      ? [
          ...candidates,
          ...fallbackItems.filter(
            (fallback) =>
              !candidates.some((item) => item.plugin_id === fallback.plugin_id) &&
              !(candidatesHaveBrowserHistory && isBrowserHistoryPlugin(fallback.plugin_id)),
          ),
        ]
      : candidates;
    const fromInstallable = collectWithMeta(mergedCandidates);
    if (fromInstallable.length > 0) {
      return fromInstallable.slice(0, MAX_EMPTY_STATE_CARDS);
    }

    return collectWithMeta(fallbackItems).slice(0, MAX_EMPTY_STATE_CARDS);
  }, [items, excluded, fallbackPluginIds, fillWithFallback]);

  if (loading && visible.length === 0) {
    // Suppress flash-of-cards while the installable list is in flight, unless
    // the caller supplied conservative fallback cards for a must-not-blank
    // surface such as onboarding completion.
    return null;
  }

  // "Browse all plugins" always-available exit into the full marketplace —
  // rendered even when no cards are available on this device, so the user is
  // never left without a way in.
  const browseAll = showBrowseAll ? (
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
  ) : null;

  if (visible.length === 0) {
    // No device-available, whitelisted cards — still surface the marketplace
    // exit rather than rendering nothing.
    return browseAll ? <div className="text-left">{browseAll}</div> : null;
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
              const options = { install: !item.installed };
              openPanel(pluginId, {
                ...options,
                ...(panelContext !== 'default' ? { context: panelContext } : {}),
                ...(onConnectDone ? { onDone: () => onConnectDone(pluginId) } : {}),
              });
              onConnectStart?.(pluginId, options);
            }}
          />
        ))}
      </div>
      {browseAll}
    </div>
  );
}

export default EmptyStateAvailableSensors;
