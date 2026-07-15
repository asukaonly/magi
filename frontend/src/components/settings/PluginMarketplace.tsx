import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  Download,
  ExternalLink,
  Loader2,
  Lock,
  Package,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import {
  pluginsApi,
  type PluginCapability,
  type PluginInstallJobSnapshot,
  type PluginManifest,
  type PluginPackageState,
  type PluginRegistryEntry,
} from '@/api/modules/plugins';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { PluginInstallProgressPanel } from '@/components/plugins/PluginInstallProgressPanel';
import { PluginConsentDialog, type ConsentMode } from '@/components/plugins/PluginConsentDialog';
import { capabilitiesExceedingConsent } from '@/lib/pluginCapabilities';
import { cn } from '@/lib/utils';
import {
  buildMarketplacePluginDisplayItems,
  getMarketplaceEntryMemberName,
  getMarketplaceItemCapabilities,
  getMarketplaceItemContributionTypes,
  getMarketplaceItemDescription,
  getMarketplaceItemIcon,
  getMarketplaceItemMemberNames,
  getMarketplaceItemName,
  localizedPluginText,
  type MarketplacePluginDisplayItem,
} from '@/utils/plugin-display-groups';

const CONTRIBUTION_TYPE_FILTERS = ['all', 'sensor', 'tool', 'channel'] as const;
type ContributionFilter = (typeof CONTRIBUTION_TYPE_FILTERS)[number];

interface EntryPickerState {
  item: MarketplacePluginDisplayItem;
  selectedIds: string[];
}

/** Resolve the localized text from an i18n map, falling back to the default. */
function localized(
  base: string,
  i18nMap: Record<string, string> | undefined,
  lang: string,
): string {
  return localizedPluginText(base, i18nMap, lang);
}

interface PluginMarketplaceProps {
  installedPlugins: PluginPackageState[];
  onInstallComplete: () => Promise<void>;
}

export const PluginMarketplace: React.FC<PluginMarketplaceProps> = ({
  installedPlugins,
  onInstallComplete,
}) => {
  const { t, i18n } = useTranslation('app');
  const language = i18n?.language ?? 'zh-CN';
  const [registryEntries, setRegistryEntries] = useState<PluginRegistryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ContributionFilter>('all');
  const [processingIds, setProcessingIds] = useState<Record<string, string>>({});
  const [installSnapshots, setInstallSnapshots] = useState<Record<string, PluginInstallJobSnapshot>>({});
  const [entryPicker, setEntryPicker] = useState<EntryPickerState | null>(null);
  const [consent, setConsent] = useState<{
    mode: ConsentMode;
    name: string;
    pluginId?: string;
    icon?: string | null;
    version: string;
    official?: boolean;
    capabilities: PluginCapability[];
    newCapabilities?: PluginCapability[];
    proceed: () => Promise<void>;
  } | null>(null);

  const fetchRegistry = useCallback(async (options?: { force?: boolean }) => {
    setLoading(true);
    setError(null);
    try {
      const response = await pluginsApi.getRegistry(options);
      setRegistryEntries(response.plugins);
    } catch (err: any) {
      const message = err?.message || 'unknown';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchRegistry();
  }, [fetchRegistry]);

  const installedIds = new Set(installedPlugins.map((p) => p.manifest.plugin_id));

  const currentPlatform = /mac/i.test(navigator.userAgent) ? 'macos' : 'windows';

  const platformEntries = useMemo(() => registryEntries.filter((entry) => {
    // Hide plugins that don't support the current platform.
    if (entry.platforms.length > 0 && !entry.platforms.includes(currentPlatform)) {
      return false;
    }
    return true;
  }), [registryEntries, currentPlatform]);

  const marketplaceItems = useMemo(
    () => buildMarketplacePluginDisplayItems(platformEntries),
    [platformEntries],
  );

  const filteredItems = useMemo(() => marketplaceItems.filter((item) => {
    const contributionTypes = getMarketplaceItemContributionTypes(item);
    // Category filter.
    if (typeFilter !== 'all' && !contributionTypes.includes(typeFilter)) {
      return false;
    }
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    const name = getMarketplaceItemName(item, language);
    const description = getMarketplaceItemDescription(item, language);
    const memberNames = getMarketplaceItemMemberNames(item, language);
    return (
      name.toLowerCase().includes(query) ||
      item.id.toLowerCase().includes(query) ||
      description.toLowerCase().includes(query) ||
      item.entries.some((entry) => entry.author.toLowerCase().includes(query)) ||
      memberNames.some((member) => member.toLowerCase().includes(query))
    );
  }), [marketplaceItems, typeFilter, searchQuery, language]);

  const isEntryInstalled = (entry: PluginRegistryEntry): boolean =>
    installedIds.has(entry.plugin_id) || entry.installed;

  const isItemInstalled = (item: MarketplacePluginDisplayItem): boolean =>
    item.entries.some(isEntryInstalled);

  const getInstallableEntries = (item: MarketplacePluginDisplayItem): PluginRegistryEntry[] =>
    item.entries.filter((entry) => !isEntryInstalled(entry));

  const getEntryCapabilities = (entries: PluginRegistryEntry[]): PluginCapability[] => {
    const seen = new Set<string>();
    const capabilities: PluginCapability[] = [];
    for (const capability of entries.flatMap((entry) => entry.capabilities ?? [])) {
      const key = JSON.stringify({
        capability: capability.capability,
        scope: capability.scope ?? [],
        optional: capability.optional ?? false,
        reason: capability.reason ?? '',
        reason_i18n: capability.reason_i18n ?? {},
      });
      if (seen.has(key)) continue;
      seen.add(key);
      capabilities.push(capability);
    }
    return capabilities;
  };

  const runInstall = async (
    item: MarketplacePluginDisplayItem,
    selectedEntries: PluginRegistryEntry[] = getInstallableEntries(item),
  ) => {
    if (selectedEntries.length === 0) {
      return;
    }
    setProcessingIds((prev) => ({ ...prev, [item.id]: 'installing' }));
    try {
      for (const entry of selectedEntries) {
        await pluginsApi.installFromRegistryWithProgress(entry.plugin_id, (snapshot) => {
          setInstallSnapshots((prev) => ({ ...prev, [entry.plugin_id]: snapshot }));
        });
      }
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n[item.id]; return n; });
    }
  };

  const handleInstall = (item: MarketplacePluginDisplayItem) => {
    const installableEntries = getInstallableEntries(item);
    if (item.kind === 'group') {
      setEntryPicker({
        item,
        selectedIds: installableEntries.map((entry) => entry.plugin_id),
      });
      return;
    }
    if (installableEntries.length === 0) {
      return;
    }
    setConsent({
      mode: 'install',
      name: getMarketplaceItemName(item, language),
      pluginId: item.id,
      icon: getMarketplaceItemIcon(item),
      version: item.primary.version,
      official: installableEntries.every((entry) => entry.official),
      capabilities: getEntryCapabilities(installableEntries),
      proceed: () => runInstall(item, installableEntries),
    });
  };

  const toggleEntryPickerSelection = (pluginId: string) => {
    setEntryPicker((prev) => {
      if (!prev) return prev;
      const selected = new Set(prev.selectedIds);
      if (selected.has(pluginId)) {
        selected.delete(pluginId);
      } else {
        selected.add(pluginId);
      }
      return {
        ...prev,
        selectedIds: [...selected],
      };
    });
  };

  const confirmEntryPickerSelection = () => {
    if (!entryPicker) {
      return;
    }
    const selected = new Set(entryPicker.selectedIds);
    const selectedEntries = entryPicker.item.entries.filter(
      (entry) => selected.has(entry.plugin_id) && !isEntryInstalled(entry)
    );
    if (selectedEntries.length === 0) {
      return;
    }
    const item = entryPicker.item;
    setEntryPicker(null);
    setConsent({
      mode: 'install',
      name: getMarketplaceItemName(item, language),
      pluginId: item.id,
      icon: getMarketplaceItemIcon(item),
      version: item.primary.version,
      official: selectedEntries.every((entry) => entry.official),
      capabilities: getEntryCapabilities(selectedEntries),
      proceed: () => runInstall(item, selectedEntries),
    });
  };

  const handleUninstall = async (item: MarketplacePluginDisplayItem) => {
    setProcessingIds((prev) => ({ ...prev, [item.id]: 'uninstalling' }));
    try {
      for (const entry of item.entries) {
        if (!isEntryInstalled(entry)) continue;
        await pluginsApi.uninstall(entry.plugin_id);
      }
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.uninstallSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      const message = err?.message || 'unknown';
      toast.error(t('settings.marketplace.feedback.uninstallFailed', { message }));
    } finally {
      setProcessingIds((prev) => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
    }
  };

  const runUpdate = async (item: MarketplacePluginDisplayItem) => {
    setProcessingIds((prev) => ({ ...prev, [item.id]: 'updating' }));
    try {
      for (const entry of item.entries) {
        if (!entry.update_available) continue;
        await pluginsApi.updatePluginWithProgress(entry.plugin_id, (snapshot) => {
          setInstallSnapshots((prev) => ({ ...prev, [entry.plugin_id]: snapshot }));
        });
      }
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.updateSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.updateFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n[item.id]; return n; });
    }
  };

  const handleUpdate = (item: MarketplacePluginDisplayItem) => {
    const declared = getMarketplaceItemCapabilities(item);
    const consented = item.entries.flatMap((entry) => {
      const installed = installedPlugins.find((p) => p.manifest.plugin_id === entry.plugin_id);
      return installed?.manifest.consented_capabilities ?? [];
    });
    const newCaps = capabilitiesExceedingConsent(declared, consented.length > 0 ? consented : null);
    if (newCaps.length === 0) {
      void runUpdate(item);
      return;
    }
    setConsent({
      mode: 'update',
      name: getMarketplaceItemName(item, language),
      pluginId: item.id,
      icon: getMarketplaceItemIcon(item),
      version: item.primary.version,
      official: item.entries.every((entry) => entry.official),
      capabilities: declared,
      newCapabilities: newCaps,
      proceed: () => runUpdate(item),
    });
  };

  const runUpload = async (file: File) => {
    setProcessingIds((prev) => ({ ...prev, __upload: 'uploading' }));
    try {
      await pluginsApi.installFromUploadWithProgress(file, (snapshot) => {
        setInstallSnapshots((prev) => ({ ...prev, __upload: snapshot }));
      });
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n.__upload; return n; });
    }
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setProcessingIds((prev) => ({ ...prev, __upload: 'uploading' }));
    let manifest: PluginManifest;
    try {
      manifest = await pluginsApi.inspectUpload(file);
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
      setProcessingIds((prev) => { const n = { ...prev }; delete n.__upload; return n; });
      return;
    }
    setProcessingIds((prev) => { const n = { ...prev }; delete n.__upload; return n; });
    setConsent({
      mode: 'sideload',
      name: manifest.name,
      pluginId: manifest.plugin_id,
      icon: manifest.icon,
      version: manifest.version,
      capabilities: manifest.capabilities ?? [],
      proceed: () => runUpload(file),
    });
  };

  return (
    <div className="space-y-4 pt-1">
      {/* Search + Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative min-w-[260px] max-w-xl flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-9 rounded-lg border-0 bg-[hsl(var(--settings-shell-elevated)/0.46)] pl-9 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.32)] focus-visible:ring-2 focus-visible:ring-primary/15 focus-visible:ring-offset-0"
            placeholder={t('settings.marketplace.searchPlaceholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-2">
          <label>
            <input
              type="file"
              accept=".tar.gz,.tgz,.zip"
              className="hidden"
              onChange={handleUpload}
              disabled={!!processingIds.__upload}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              asChild
              disabled={!!processingIds.__upload}
              className="h-9 rounded-lg bg-transparent px-3.5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34)] hover:bg-[hsl(var(--settings-nav-hover)/0.42)]"
            >
              <span>
                <Package className="mr-2 h-4 w-4" />
                {t('settings.marketplace.actions.uploadPlugin')}
              </span>
            </Button>
          </label>

          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={t('settings.marketplace.actions.refresh')}
            title={t('settings.marketplace.actions.refresh')}
            onClick={() => void fetchRegistry({ force: true })}
            disabled={loading}
            className="h-9 w-9 rounded-lg bg-transparent shadow-none hover:bg-[hsl(var(--settings-nav-hover)/0.42)]"
          >
            <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          </Button>
        </div>
      </div>

      {/* Category filter */}
      <nav
        className="flex flex-wrap items-center gap-5 border-b border-[hsl(var(--settings-subnav-border)/0.36)]"
        aria-label={t('settings.marketplace.filterLabel')}
      >
        {CONTRIBUTION_TYPE_FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            aria-pressed={typeFilter === filter}
            className={cn(
              'relative inline-flex h-10 items-center px-0.5 text-sm transition-colors duration-200 after:absolute after:inset-x-0 after:bottom-[-1px] after:h-0.5 after:origin-center after:rounded-sm after:bg-primary after:transition-transform after:duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15',
              typeFilter === filter
                ? 'font-semibold text-foreground after:scale-x-100'
                : 'font-medium text-muted-foreground after:scale-x-0 hover:text-foreground'
            )}
            onClick={() => setTypeFilter(filter)}
          >
            {t(`settings.marketplace.filter.${filter}`)}
          </button>
        ))}
      </nav>

      {installSnapshots.__upload ? (
        <PluginInstallProgressPanel
          snapshot={installSnapshots.__upload}
          title={t('settings.marketplace.installProgress.uploadTitle')}
        />
      ) : null}

      {/* Content */}
      {loading && registryEntries.length === 0 ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          <span className="text-sm">{t('settings.marketplace.loading')}</span>
        </div>
      ) : error ? (
        <div className="space-y-3 py-8 text-center">
          <p className="text-sm text-destructive">{t('settings.marketplace.error')}</p>
          <p className="text-xs text-muted-foreground">{error}</p>
          <Button type="button" variant="outline" size="sm" onClick={() => void fetchRegistry({ force: true })}>
            {t('settings.marketplace.actions.retry')}
          </Button>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          {searchQuery
            ? t('settings.marketplace.noResults')
            : t('settings.marketplace.empty')}
        </div>
      ) : (
        <div
          data-testid="marketplace-list"
          className="divide-y divide-[hsl(var(--settings-subnav-border)/0.34)]"
        >
          {filteredItems.map((item) => {
            const entry = item.primary;
            const itemName = getMarketplaceItemName(item, language);
            const itemDescription = getMarketplaceItemDescription(item, language);
            const contributionTypes = getMarketplaceItemContributionTypes(item);
            const isInstalled = isItemInstalled(item);
            const installedCount = item.entries.filter(isEntryInstalled).length;
            const installableEntries = getInstallableEntries(item);
            const allEntriesInstalled = item.kind === 'group' && installedCount === item.entries.length;
            const hasInstallableEntries = installableEntries.length > 0;
            const operation = processingIds[item.id]
              || item.entries.map((candidate) => processingIds[candidate.plugin_id]).find(Boolean);
            const isProcessing = !!operation;
            const updateAvailable = item.entries.some((candidate) => candidate.update_available);
            const allOfficial = item.entries.every((candidate) => candidate.official);
            const dataLocalOnly = item.entries.every((candidate) => candidate.data_locality === 'local_only');
            const headlineMeta = [
              `v${entry.version}`,
              item.kind === 'group'
                ? t('settings.marketplace.badge.entryCount', { count: item.entries.length })
                : null,
              item.kind === 'group' && installedCount > 0
                ? (allEntriesInstalled
                  ? t('settings.marketplace.badge.installedAll')
                  : t('settings.marketplace.badge.installedPartial', {
                    installed: installedCount,
                    total: item.entries.length,
                  }))
                : null,
            ].filter((value): value is string => Boolean(value));
            const supportingMeta = [
              entry.author || null,
              allOfficial ? t('settings.marketplace.badge.official') : null,
              ...contributionTypes.map((type) => t(
                `settings.marketplace.contributionType.${type}`,
                { defaultValue: type },
              )),
            ].filter((value): value is string => Boolean(value));
            const entrySnapshots = item.entries
              .map((candidate) => installSnapshots[candidate.plugin_id])
              .filter(Boolean);
            const groupedSnapshot = item.kind === 'group'
              ? (
                entrySnapshots.find((snapshot) => snapshot.status === 'queued' || snapshot.status === 'running')
                || entrySnapshots[entrySnapshots.length - 1]
              )
              : null;

            return (
              <article
                key={item.id}
                data-testid={`marketplace-plugin-${item.id}`}
                className="-mx-3 space-y-3 rounded-lg px-3 py-5 transition-colors duration-200 hover:bg-[hsl(var(--settings-shell-elevated)/0.28)]"
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                  <div className="flex min-w-0 flex-1 gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center text-foreground">
                      <PluginIcon
                        iconId={getMarketplaceItemIcon(item)}
                        className="h-6 w-6"
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="text-[15px] font-semibold leading-6 text-foreground">
                          {itemName}
                        </span>
                        {headlineMeta.map((label, index) => (
                          <React.Fragment key={label}>
                            {index > 0 ? (
                              <span aria-hidden className="text-[10px] text-muted-foreground/55">·</span>
                            ) : null}
                            <span className="text-xs font-medium text-muted-foreground">
                              {label}
                            </span>
                          </React.Fragment>
                        ))}
                      </div>
                      <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
                        {itemDescription}
                      </p>
                      {item.kind === 'group' ? (
                        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                          {item.entries.map((candidate) => {
                            const candidateInstalled = isEntryInstalled(candidate);
                            const memberName = getMarketplaceEntryMemberName(candidate, language);
                            return (
                              <span
                                key={candidate.plugin_id}
                                data-testid={`marketplace-entry-chip-${candidate.plugin_id}`}
                                className="inline-flex items-center gap-1.5"
                              >
                                {candidateInstalled ? (
                                  <Check className="h-3 w-3 text-primary" />
                                ) : null}
                                <span className="font-medium text-[hsl(var(--settings-nav-foreground))]">
                                  {memberName}
                                </span>
                                <span className="text-[11px] text-muted-foreground">
                                  {candidateInstalled
                                    ? t('settings.marketplace.entryStatus.installed')
                                    : t('settings.marketplace.entryStatus.available')}
                                </span>
                              </span>
                            );
                          })}
                        </div>
                      ) : null}
                      <div
                        data-testid={`marketplace-plugin-meta-${item.id}`}
                        className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
                      >
                        {supportingMeta.map((label, index) => (
                          <React.Fragment key={`${label}-${index}`}>
                            {index > 0 ? <span aria-hidden className="opacity-55">·</span> : null}
                            <span>{label}</span>
                          </React.Fragment>
                        ))}
                        {dataLocalOnly ? (
                          <>
                            {supportingMeta.length > 0 ? (
                              <span aria-hidden className="opacity-55">·</span>
                            ) : null}
                            <span
                              className="inline-flex items-center gap-1"
                              title={t('settings.marketplace.badge.localOnlyHint')}
                            >
                              <Lock className="h-3 w-3" />
                              {t('settings.marketplace.badge.localOnly')}
                            </span>
                          </>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-1 self-start sm:ml-2">
                    {entry.homepage && (
                      <a
                        href={entry.homepage}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={t('settings.marketplace.actions.openHomepage')}
                        title={t('settings.marketplace.actions.openHomepage')}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[hsl(var(--settings-nav-hover)/0.72)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    )}

                    {item.kind === 'group' ? (
                      <div className="flex items-center gap-2">
                        {updateAvailable && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={isProcessing}
                            onClick={() => handleUpdate(item)}
                            className="h-9 rounded-lg bg-transparent px-3.5 shadow-none hover:bg-[hsl(var(--settings-nav-hover)/0.42)]"
                          >
                            {operation === 'updating' ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <RefreshCw className="mr-2 h-4 w-4" />
                            )}
                            {t('settings.marketplace.actions.update')}
                          </Button>
                        )}
                        {hasInstallableEntries ? (
                          <Button
                            type="button"
                            variant="default"
                            size="sm"
                            disabled={isProcessing}
                            onClick={() => handleInstall(item)}
                            className="h-9 rounded-lg px-4 shadow-none hover:shadow-none"
                          >
                            {operation === 'installing' ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : installedCount > 0 ? (
                              <Plus className="mr-2 h-4 w-4" />
                            ) : (
                              <Download className="mr-2 h-4 w-4" />
                            )}
                            {installedCount > 0
                              ? t('settings.marketplace.actions.addEntries')
                              : t('settings.marketplace.actions.chooseEntries')}
                          </Button>
                        ) : (
                          <span className="inline-flex h-9 items-center gap-1.5 px-2 text-xs font-medium text-muted-foreground">
                            <Check className="h-3.5 w-3.5 text-primary" />
                            {t('settings.marketplace.badge.installedAll')}
                          </span>
                        )}
                      </div>
                    ) : isInstalled ? (
                      <div className="flex items-center gap-2">
                        {updateAvailable && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={isProcessing}
                            onClick={() => handleUpdate(item)}
                            className="h-9 rounded-lg bg-transparent px-3.5 shadow-none hover:bg-[hsl(var(--settings-nav-hover)/0.42)]"
                          >
                            {operation === 'updating' ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <RefreshCw className="mr-2 h-4 w-4" />
                            )}
                            {t('settings.marketplace.actions.update')}
                            {item.kind === 'single' && entry.installed_version && (
                              <span className="ml-1 text-xs text-muted-foreground">
                                {entry.installed_version} → {entry.version}
                              </span>
                            )}
                          </Button>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t('settings.marketplace.actions.uninstall')}
                          title={t('settings.marketplace.actions.uninstall')}
                          disabled={isProcessing}
                          onClick={() => void handleUninstall(item)}
                          className="h-9 w-9 rounded-lg text-muted-foreground hover:bg-destructive/5 hover:text-destructive"
                        >
                          {operation === 'uninstalling' ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </Button>
                        <span className="inline-flex h-9 items-center gap-1.5 px-2 text-xs font-medium text-muted-foreground">
                          <Check className="h-3.5 w-3.5 text-primary" />
                          {t('settings.marketplace.badge.installed')}
                        </span>
                      </div>
                    ) : (
                      <Button
                        type="button"
                        variant="default"
                        size="sm"
                        disabled={isProcessing}
                        onClick={() => handleInstall(item)}
                        className="h-9 rounded-lg px-4 shadow-none hover:shadow-none"
                      >
                        {operation === 'installing' ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Download className="mr-2 h-4 w-4" />
                        )}
                        {t('settings.marketplace.actions.install')}
                      </Button>
                    )}
                  </div>
                </div>

                {groupedSnapshot ? (
                  <PluginInstallProgressPanel
                    snapshot={groupedSnapshot}
                    title={t('settings.marketplace.installProgress.groupTitle', { name: itemName })}
                  />
                ) : (
                  item.entries.map((candidate) => (
                    installSnapshots[candidate.plugin_id] ? (
                      <PluginInstallProgressPanel
                        key={candidate.plugin_id}
                        snapshot={installSnapshots[candidate.plugin_id]}
                        title={t('settings.marketplace.installProgress.itemTitle', {
                          name: localized(candidate.name, candidate.name_i18n, language),
                        })}
                      />
                    ) : null
                  ))
                )}
              </article>
            );
          })}
        </div>
      )}

      {entryPicker ? (
        <Dialog open onOpenChange={(open) => { if (!open) setEntryPicker(null); }}>
          <DialogContent
            className="max-w-xl overflow-hidden p-0"
            data-testid={`marketplace-entry-picker-${entryPicker.item.id}`}
          >
            <DialogHeader className="px-6 pb-2 pt-6">
              <DialogTitle className="text-base">
                {t('settings.marketplace.entryPicker.title', {
                  name: getMarketplaceItemName(entryPicker.item, language),
                })}
              </DialogTitle>
              <DialogDescription className="leading-6">
                {t('settings.marketplace.entryPicker.description')}
              </DialogDescription>
            </DialogHeader>
            <div className="divide-y divide-[hsl(var(--settings-subnav-border)/0.3)] px-6 py-3">
              {entryPicker.item.entries.map((candidate) => {
                const candidateInstalled = isEntryInstalled(candidate);
                const checked = candidateInstalled || entryPicker.selectedIds.includes(candidate.plugin_id);
                const memberName = getMarketplaceEntryMemberName(candidate, language);
                return (
                  <label
                    key={candidate.plugin_id}
                    data-testid={`marketplace-entry-option-${candidate.plugin_id}`}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-md px-2 py-3 transition-colors duration-200',
                      candidateInstalled
                        ? 'cursor-default text-muted-foreground'
                        : 'hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]'
                    )}
                  >
                    <input
                      type="checkbox"
                      data-testid={`marketplace-entry-checkbox-${candidate.plugin_id}`}
                      checked={checked}
                      disabled={candidateInstalled}
                      onChange={() => toggleEntryPickerSelection(candidate.plugin_id)}
                      className="mt-1 h-4 w-4 rounded border-[hsl(var(--settings-subnav-border))] accent-[hsl(var(--primary))]"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <PluginIcon
                          iconId={candidate.icon || candidate.display_group?.icon}
                          className="h-4 w-4"
                        />
                        <span className="text-sm font-semibold text-foreground">{memberName}</span>
                        <span
                          className={cn(
                            'text-xs font-medium',
                            candidateInstalled ? 'text-primary' : 'text-muted-foreground'
                          )}
                        >
                          {candidateInstalled
                            ? t('settings.marketplace.entryStatus.installed')
                            : t('settings.marketplace.entryStatus.available')}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {localized(candidate.description, candidate.description_i18n, language)}
                      </p>
                    </div>
                  </label>
                );
              })}
            </div>
            <DialogFooter className="border-t-0 px-6 pb-6 pt-2">
              <Button type="button" variant="ghost" onClick={() => setEntryPicker(null)}>
                {t('settings.marketplace.entryPicker.cancel')}
              </Button>
              <Button
                type="button"
                disabled={entryPicker.selectedIds.length === 0}
                onClick={confirmEntryPickerSelection}
              >
                {t('settings.marketplace.entryPicker.confirm')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}

      {consent && (
        <PluginConsentDialog
          open
          mode={consent.mode}
          pluginName={consent.name}
          pluginIcon={consent.icon}
          version={consent.version}
          official={consent.official}
          capabilities={consent.capabilities}
          newCapabilities={consent.newCapabilities}
          onCancel={() => setConsent(null)}
          onConfirm={() => { const p = consent.proceed; setConsent(null); void p(); }}
        />
      )}
    </div>
  );
};

export default PluginMarketplace;
