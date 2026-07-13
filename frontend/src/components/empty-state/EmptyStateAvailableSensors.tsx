import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useInstallableSensors } from "../../hooks/useInstallableSensors";
import {
  usePluginInstallPanelStore,
  type PluginInstallDoneInfo,
  type PluginInstallPanelContext,
} from "../../stores/pluginInstallPanel";
import { useChatShellStore } from "../../stores/chat-shell";
import {
  BROWSER_HISTORY_PRIORITY_PLUGINS,
  EMPTY_STATE_PRIORITY_PLUGINS,
  FIRST_CONTEXT_PRIORITY_PLUGINS,
  getEmptyStatePluginMeta,
  type EmptyStatePluginMeta,
} from "../../constants/emptyStatePriorities";
import type { InstallableItem } from "../../api/modules/systemSuggestions";
import { EmptyStateSensorCard } from "./EmptyStateSensorCard";

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
  variant?: "standard" | "first_context";
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
  installableError?: Error | null;
  onRetryInstallable?: () => void;
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
  onConnectDone?: (pluginId: string, info?: PluginInstallDoneInfo) => void;
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
function priorityIndex(pluginId: string, firstContext = false): number {
  if (
    (BROWSER_HISTORY_PRIORITY_PLUGINS as readonly string[]).includes(pluginId)
  ) {
    return 0;
  }
  const priorities = firstContext
    ? (FIRST_CONTEXT_PRIORITY_PLUGINS as readonly string[])
    : (EMPTY_STATE_PRIORITY_PLUGINS as readonly string[]);
  const idx = priorities.indexOf(pluginId);
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

function browserHistoryIndex(pluginId: string): number {
  const idx = (BROWSER_HISTORY_PRIORITY_PLUGINS as readonly string[]).indexOf(
    pluginId,
  );
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

function isBrowserHistoryPlugin(pluginId: string): boolean {
  return browserHistoryIndex(pluginId) !== Number.MAX_SAFE_INTEGER;
}

function isKnownPlugin(pluginId: string, firstContext = false): boolean {
  return priorityIndex(pluginId, firstContext) !== Number.MAX_SAFE_INTEGER;
}

/**
 * Hard cap on how many cards the empty-state list renders. Items beyond the
 * top-N (by priority, after dropping metadata-less ones) stay behind the
 * "Browse all plugins" marketplace exit rather than growing the list.
 */
const MAX_EMPTY_STATE_CARDS = 5;

export function EmptyStateAvailableSensors({
  variant = "standard",
  excludePluginIds,
  i18nNamespace = "onboarding",
  i18nKeyPrefix,
  showBrowseAll = true,
  fallbackPluginIds,
  fillWithFallback = false,
  installableItems,
  installableLoading,
  installableError,
  onRetryInstallable,
  onConnectStart,
  onConnectDone,
  panelContext = "default",
}: EmptyStateAvailableSensorsProps): JSX.Element | null {
  const { t } = useTranslation(i18nNamespace);
  const keyed = (key: string) =>
    i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key;

  const hookState = useInstallableSensors(installableItems === undefined);
  const items = installableItems ?? hookState.items ?? [];
  const loading = installableLoading ?? hookState.loading;
  const error =
    installableError === undefined ? hookState.error : installableError;
  const retryInstallable = onRetryInstallable ?? hookState.refresh;
  const firstContext = variant === "first_context";

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
  const visible = useMemo<
    { item: InstallableItem; meta: EmptyStatePluginMeta }[]
  >(() => {
    const collectWithMeta = (
      sourceItems: InstallableItem[],
      useFirstContext = false,
    ) => {
      const browserHistory = [...sourceItems]
        .filter((item) => isBrowserHistoryPlugin(item.plugin_id))
        .sort(
          (a, b) =>
            browserHistoryIndex(a.plugin_id) - browserHistoryIndex(b.plugin_id),
        )
        .slice(0, useFirstContext ? undefined : 1);
      const otherItems = sourceItems.filter(
        (item) => !isBrowserHistoryPlugin(item.plugin_id),
      );
      const sorted = [...browserHistory, ...otherItems].sort(
        (a, b) =>
          priorityIndex(a.plugin_id, useFirstContext) -
          priorityIndex(b.plugin_id, useFirstContext),
      );
      const withMeta: { item: InstallableItem; meta: EmptyStatePluginMeta }[] =
        [];
      for (const item of sorted) {
        const meta = getEmptyStatePluginMeta(item.plugin_id);
        if (meta && isKnownPlugin(item.plugin_id, useFirstContext)) {
          withMeta.push({ item, meta });
        }
      }
      return withMeta;
    };

    const fallbackItems = (fallbackPluginIds ?? [])
      .filter((pluginId) => !excluded.has(pluginId))
      .map((pluginId) => ({
        plugin_id: pluginId,
        category: "onboarding_fallback",
        installed: false,
        rationale: { zh: "", en: "" },
        setup_time_estimate_seconds: 30,
        data_locality: "local_only" as const,
      }));

    const candidates = items.filter((item) => !excluded.has(item.plugin_id));
    if (firstContext) {
      const excludedCategories = new Set(
        [...excluded].map((pluginId) => {
          const metaCategory =
            getEmptyStatePluginMeta(pluginId)?.recommendationCategory;
          const itemCategory = items.find(
            (item) => item.plugin_id === pluginId,
          )?.category;
          return metaCategory || itemCategory || pluginId;
        }),
      );
      const eligible = collectWithMeta(
        candidates.filter(
          (item) => {
            const category =
              getEmptyStatePluginMeta(item.plugin_id)
                ?.recommendationCategory ||
              item.category ||
              item.plugin_id;
            return !excludedCategories.has(category);
          },
        ),
        true,
      ).sort((a, b) => {
        if (a.item.installed !== b.item.installed) {
          return a.item.installed ? -1 : 1;
        }
        const priorityDelta =
          priorityIndex(a.item.plugin_id, true) -
          priorityIndex(b.item.plugin_id, true);
        if (priorityDelta !== 0) {
          return priorityDelta;
        }
        return (
          a.item.setup_time_estimate_seconds -
          b.item.setup_time_estimate_seconds
        );
      });
      const categoryRepresentatives = new Map<
        string,
        { item: InstallableItem; meta: EmptyStatePluginMeta }
      >();
      for (const candidate of eligible) {
        const category =
          candidate.meta.recommendationCategory ||
          candidate.item.category ||
          candidate.item.plugin_id;
        if (!categoryRepresentatives.has(category)) {
          categoryRepresentatives.set(category, candidate);
        }
      }
      return [...categoryRepresentatives.values()].slice(0, 3);
    }
    const candidatesHaveBrowserHistory = candidates.some((item) =>
      isBrowserHistoryPlugin(item.plugin_id),
    );
    const mergedCandidates = fillWithFallback
      ? [
          ...candidates,
          ...fallbackItems.filter(
            (fallback) =>
              !candidates.some(
                (item) => item.plugin_id === fallback.plugin_id,
              ) &&
              !(
                candidatesHaveBrowserHistory &&
                isBrowserHistoryPlugin(fallback.plugin_id)
              ),
          ),
        ]
      : candidates;
    const fromInstallable = collectWithMeta(mergedCandidates);
    if (fromInstallable.length > 0) {
      return fromInstallable.slice(0, MAX_EMPTY_STATE_CARDS);
    }

    return collectWithMeta(fallbackItems).slice(0, MAX_EMPTY_STATE_CARDS);
  }, [items, excluded, fallbackPluginIds, fillWithFallback, firstContext]);

  if (firstContext && loading && visible.length === 0) {
    return (
      <div className="rounded-xl border border-border/45 bg-muted/20 px-4 py-5 text-sm text-muted-foreground">
        {t(keyed("emptyState.checking"))}
      </div>
    );
  }

  if (firstContext && error && visible.length === 0) {
    return (
      <div className="flex items-center justify-between gap-4 rounded-xl border border-border/50 bg-muted/20 px-4 py-4">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">
            {t(keyed("emptyState.loadErrorTitle"))}
          </p>
          <p className="text-xs leading-5 text-muted-foreground">
            {t(keyed("emptyState.loadError"))}
          </p>
        </div>
        <button
          type="button"
          data-testid="empty-state-retry"
          onClick={retryInstallable}
          className="shrink-0 rounded-md border border-primary/30 bg-background px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
        >
          {t(keyed("emptyState.retry"))}
        </button>
      </div>
    );
  }

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
        setSettingsNavigationIntent({ section: "pluginsMarketplace" });
        setActivePanel("settings");
      }}
      className="text-xs font-semibold text-muted-foreground transition hover:text-foreground"
    >
      {t(keyed("emptyState.browseAll"))}
    </button>
  ) : null;

  if (visible.length === 0) {
    if (firstContext) {
      return (
        <div className="rounded-xl border border-border/45 bg-muted/20 px-4 py-4">
          <p className="text-sm font-medium text-foreground">
            {t(keyed("emptyState.noAvailable"))}
          </p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {t(keyed("emptyState.noAvailableHint"))}
          </p>
        </div>
      );
    }
    // No device-available, whitelisted cards — still surface the marketplace
    // exit rather than rendering nothing.
    return browseAll ? <div className="text-left">{browseAll}</div> : null;
  }

  if (firstContext) {
    const [featured, ...alternatives] = visible;
    const cardProps = ({
      item,
      meta,
    }: {
      item: InstallableItem;
      meta: EmptyStatePluginMeta;
    }) => ({
      pluginId: item.plugin_id,
      titleKey: meta.titleKey,
      valueKey: meta.firstContextValueKey ?? meta.valueKey,
      iconId: meta.iconId,
      i18nNamespace,
      i18nKeyPrefix,
      reason: t(
        keyed(
          item.installed
            ? "emptyState.availableReasonInstalled"
            : "emptyState.availableReason",
        ),
      ),
      scope: meta.scopeKey ? t(keyed(meta.scopeKey)) : undefined,
      localityLabel: t(
        keyed(
          item.data_locality === "local_only"
            ? "emptyState.localOnly"
            : "emptyState.uploads",
        ),
      ),
      setupTimeLabel: t(keyed("emptyState.setupTime"), {
        seconds: item.setup_time_estimate_seconds,
      }),
      onConnect: (pluginId: string) => {
        const options = { install: !item.installed };
        openPanel(pluginId, {
          ...options,
          ...(panelContext !== "default" ? { context: panelContext } : {}),
          ...(onConnectDone
            ? {
                onDone: (info?: PluginInstallDoneInfo) =>
                  onConnectDone(pluginId, info),
              }
            : {}),
        });
        onConnectStart?.(pluginId, options);
      },
    });

    return (
      <div className="space-y-3 text-left">
        <h3 className="text-sm font-semibold text-foreground">
          {t(keyed("emptyState.firstContextHeading"))}
        </h3>
        <EmptyStateSensorCard
          {...cardProps(featured)}
          variant="featured"
          connectLabelKey="emptyState.reviewAndConnect"
        />
        {alternatives.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {alternatives.map((entry) => (
              <EmptyStateSensorCard
                key={entry.item.plugin_id}
                {...cardProps(entry)}
                variant="compact"
                connectLabelKey="emptyState.view"
              />
            ))}
          </div>
        ) : null}
        {browseAll}
      </div>
    );
  }

  return (
    // text-left: the timeline/memory empty states wrap this in a `text-center`
    // container; without this the inherited centering shifts each row's (short)
    // title vs (longer) description so they look misaligned.
    <div className="space-y-3 text-left">
      <h3 className="text-sm font-medium text-foreground">
        {t(keyed("emptyState.heading"))}
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
              item.installed
                ? "emptyState.connect"
                : "emptyState.installAndConnect"
            }
            onConnect={(pluginId) => {
              // Install-first for registry-only items: the panel downloads
              // from the registry before the connect flow runs.
              const options = { install: !item.installed };
              openPanel(pluginId, {
                ...options,
                ...(panelContext !== "default"
                  ? { context: panelContext }
                  : {}),
                ...(onConnectDone
                  ? {
                      onDone: (info?: PluginInstallDoneInfo) =>
                        onConnectDone(pluginId, info),
                    }
                  : {}),
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
