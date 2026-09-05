import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useInstallableSources } from "../../hooks/useInstallableSources";
import {
  usePluginInstallPanelStore,
  type PluginInstallDoneInfo,
  type PluginInstallPanelContext,
} from "../../stores/pluginInstallPanel";
import { useChatShellStore } from "../../stores/chat-shell";
import type {
  InstallableCatalogMode,
  InstallableItem,
} from "../../api/modules/systemSuggestions";
import { localizedPluginText } from "../../utils/plugin-display-groups";
import { EmptyStateSourceCard } from "./EmptyStateSourceCard";

/**
 * Orchestrator component for the empty-state CTA list.
 *
 * Responsibilities:
 *   1. Source the candidate plugins from the backend
 *      `GET /system-suggestions/installable` endpoint via
 *      `useInstallableSources`. The backend returns the availability-filtered
 *      union of locally-installed sources and registry-available plugins, each
 *      tagged with an `installed` flag.
 *   2. Render an `<EmptyStateSourceCard>` for plugins that opt into the current
 *      surface. Plugins own their copy and order; sibling implementations share
 *      one category slot.
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

export interface EmptyStateAvailableSourcesProps {
  variant?: "standard" | "first_context" | "source_page";
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
   * Optional preloaded suggestions. Onboarding uses this to avoid a blank
   * completion page while the same suggestions are already being fetched.
   */
  installableItems?: InstallableItem[];
  installableCatalogMode?: InstallableCatalogMode | null;
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
 * Hard cap on how many cards the empty-state list renders. Items beyond the
 * top-N (by plugin-declared order) stay behind the
 * "Browse all plugins" marketplace exit rather than growing the list.
 */
const MAX_EMPTY_STATE_CARDS = 5;
const MAX_FIRST_CONTEXT_CARDS = 5;
const MAX_SOURCE_PAGE_CARDS = 3;

export function EmptyStateAvailableSources({
  variant = "standard",
  excludePluginIds,
  i18nNamespace = "onboarding",
  i18nKeyPrefix,
  showBrowseAll = true,
  installableItems,
  installableCatalogMode,
  installableLoading,
  installableError,
  onRetryInstallable,
  onConnectStart,
  onConnectDone,
  panelContext = "default",
}: EmptyStateAvailableSourcesProps): JSX.Element | null {
  const { t, i18n } = useTranslation(i18nNamespace);
  const keyed = (key: string) =>
    i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key;

  const hookState = useInstallableSources(installableItems === undefined);
  const items = installableItems ?? hookState.items ?? [];
  const catalogMode =
    installableCatalogMode === undefined
      ? hookState.catalogMode
      : installableCatalogMode;
  const loading = installableLoading ?? hookState.loading;
  const error =
    installableError === undefined ? hookState.error : installableError;
  const retryInstallable = onRetryInstallable ?? hookState.refresh;
  const firstContext = variant === "first_context";
  const sourcePage = variant === "source_page";
  const marketplaceUnavailable = catalogMode === "installed_only";
  const language = i18n.resolvedLanguage ?? i18n.language;
  const localized = (
    text: { zh: string; en: string } | null | undefined,
  ): string | undefined =>
    text ? localizedPluginText(text.en, text, language) : undefined;
  const pluginName = (item: InstallableItem): string =>
    localizedPluginText(item.name, item.name_i18n, language);

  // Connect now opens the single MainLayout-mounted <PluginInstallPanel>, which
  // owns the full honest flow (install → enable → sync → build-memory) and its
  // own done state. This component no longer renders its own dialog.
  const openPanel = usePluginInstallPanelStore((s) => s.openPanel);
  const connectItem = (item: InstallableItem) => (pluginId: string) => {
    const options = { install: !item.installed };
    openPanel(pluginId, {
      ...options,
      pluginName: pluginName(item),
      pluginIcon: item.icon,
      ...(panelContext !== "default" ? { context: panelContext } : {}),
      ...(onConnectDone
        ? {
            onDone: (info?: PluginInstallDoneInfo) =>
              onConnectDone(pluginId, info),
          }
        : {}),
    });
    onConnectStart?.(pluginId, options);
  };

  // "Browse all plugins" footer deep-links into Settings → plugin marketplace,
  // the full catalog beyond the plugin-declared empty-state cards. Same intent
  // mechanism ScheduleConfigPage uses to jump into a settings section.
  const setActivePanel = useChatShellStore((s) => s.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore(
    (s) => s.setSettingsNavigationIntent,
  );

  const excluded = useMemo(
    () => new Set(excludePluginIds ?? []),
    [excludePluginIds],
  );

  // Plugins opt into each surface and own their order/copy/scope. The host only
  // groups sibling implementations by category and caps the amount shown.
  const visible = useMemo<InstallableItem[]>(() => {
    const surface = (item: InstallableItem) =>
      firstContext
        ? item.surfaces?.first_context
        : item.surfaces?.empty_state;
    const excludedCategories = new Set(
      items
        .filter((item) => excluded.has(item.plugin_id))
        .map((item) => item.category),
    );
    const grouped = new Map<string, InstallableItem[]>();
    for (const item of items) {
      if (
        excluded.has(item.plugin_id) ||
        excludedCategories.has(item.category) ||
        !surface(item)
      ) {
        continue;
      }
      const siblings = grouped.get(item.category) ?? [];
      siblings.push(item);
      grouped.set(item.category, siblings);
    }
    const representatives = [...grouped.values()].map((siblings) =>
      [...siblings].sort((a, b) => {
        if (a.installed !== b.installed) return a.installed ? -1 : 1;
        const orderDelta = (surface(a)?.order ?? 100) - (surface(b)?.order ?? 100);
        if (orderDelta !== 0) return orderDelta;
        return a.setup_time_estimate_seconds - b.setup_time_estimate_seconds;
      })[0],
    );
    representatives.sort((a, b) => {
      const orderDelta = (surface(a)?.order ?? 100) - (surface(b)?.order ?? 100);
      if (orderDelta !== 0) return orderDelta;
      if (a.installed !== b.installed) return a.installed ? -1 : 1;
      return a.setup_time_estimate_seconds - b.setup_time_estimate_seconds;
    });
    const limit = firstContext
      ? MAX_FIRST_CONTEXT_CARDS
      : sourcePage
        ? MAX_SOURCE_PAGE_CARDS
        : MAX_EMPTY_STATE_CARDS;
    return representatives.slice(0, limit);
  }, [items, excluded, firstContext, sourcePage]);

  if (firstContext && loading && visible.length === 0) {
    return (
      <div className="py-3 text-sm text-muted-foreground">
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
    // Suppress flash-of-cards while the installable list is in flight.
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
      className={
        sourcePage
          ? "inline-flex h-9 items-center justify-center rounded-lg bg-[hsl(var(--secondary)/0.86)] px-4 text-sm font-semibold text-[hsl(var(--memory-title))] transition-colors duration-200 hover:bg-secondary"
          : "text-xs font-semibold text-muted-foreground transition hover:text-foreground"
      }
    >
      {t(keyed(sourcePage ? "emptyState.browseSources" : "emptyState.browseAll"))}
    </button>
  ) : null;

  if (visible.length === 0) {
    if (firstContext) {
      if (marketplaceUnavailable) {
        return (
          <div
            data-testid="marketplace-unavailable"
            className="flex items-start justify-between gap-4 py-2"
          >
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-medium text-foreground">
                {t(keyed("emptyState.marketplaceUnavailableTitle"))}
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                {t(keyed("emptyState.marketplaceUnavailable"))}
              </p>
            </div>
            <button
              type="button"
              data-testid="empty-state-retry"
              onClick={retryInstallable}
              className="shrink-0 text-xs font-medium text-foreground underline-offset-4 transition-colors hover:text-primary hover:underline"
            >
              {t(keyed("emptyState.retry"))}
            </button>
          </div>
        );
      }
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
    // No device-available cards — still surface the marketplace
    // exit rather than rendering nothing.
    return browseAll ? <div className={sourcePage ? "pt-1 text-left" : "text-left"}>{browseAll}</div> : null;
  }

  if (firstContext) {
    const [featured, ...alternatives] = visible;
    const cardProps = (item: InstallableItem) => ({
      pluginId: item.plugin_id,
      title: pluginName(item),
      value:
        localized(item.surfaces?.first_context?.rationale) ??
        localized(item.rationale) ??
        item.description,
      iconId: item.icon,
      i18nNamespace,
      i18nKeyPrefix,
      reason: t(
        keyed(
          item.installed
            ? "emptyState.availableReasonInstalled"
            : "emptyState.availableReason",
        ),
      ),
      scope: localized(item.surfaces?.first_context?.scope),
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
      onConnect: connectItem(item),
    });

    return (
      <div className="space-y-3 text-left">
        <h3 className="text-sm font-semibold text-foreground">
          {t(keyed("emptyState.firstContextHeading"))}
        </h3>
        {marketplaceUnavailable ? (
          <div
            data-testid="marketplace-unavailable"
            className="flex items-center justify-between gap-3 text-xs leading-5 text-muted-foreground"
          >
            <span>{t(keyed("emptyState.marketplaceUnavailableWithLocal"))}</span>
            <button
              type="button"
              data-testid="empty-state-retry"
              onClick={retryInstallable}
              className="shrink-0 font-medium text-foreground underline-offset-4 transition-colors hover:text-primary hover:underline"
            >
              {t(keyed("emptyState.retry"))}
            </button>
          </div>
        ) : null}
        <EmptyStateSourceCard
          {...cardProps(featured)}
          variant="featured"
          connectLabelKey="emptyState.reviewAndConnect"
        />
        {alternatives.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {alternatives.map((entry) => (
              <EmptyStateSourceCard
                key={entry.plugin_id}
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

  if (sourcePage) {
    return (
      <div className="space-y-4 text-left" data-testid="source-page-suggestions">
        <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
          {t(keyed("emptyState.sourcePageHeading"))}
        </h2>
        <div className="divide-y divide-[hsl(var(--memory-divider)/0.32)] overflow-hidden rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.38)]">
          {visible.map((item) => (
            <EmptyStateSourceCard
              key={item.plugin_id}
              pluginId={item.plugin_id}
              title={pluginName(item)}
              value={localized(item.surfaces?.empty_state?.rationale) ?? localized(item.rationale) ?? item.description}
              iconId={item.icon}
              i18nNamespace={i18nNamespace}
              i18nKeyPrefix={i18nKeyPrefix}
              connectLabelKey={
                item.installed
                  ? "emptyState.connect"
                  : "emptyState.installAndConnect"
              }
              onConnect={connectItem(item)}
            />
          ))}
        </div>
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
        {visible.map((item) => (
          <EmptyStateSourceCard
            key={item.plugin_id}
            pluginId={item.plugin_id}
            title={pluginName(item)}
            value={localized(item.surfaces?.empty_state?.rationale) ?? localized(item.rationale) ?? item.description}
            iconId={item.icon}
            i18nNamespace={i18nNamespace}
            i18nKeyPrefix={i18nKeyPrefix}
            connectLabelKey={
              item.installed
                ? "emptyState.connect"
                : "emptyState.installAndConnect"
            }
            onConnect={connectItem(item)}
          />
        ))}
      </div>
      {browseAll}
    </div>
  );
}

export default EmptyStateAvailableSources;
