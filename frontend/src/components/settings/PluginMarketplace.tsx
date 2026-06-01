import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Download,
  ExternalLink,
  Loader2,
  Package,
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PluginInstallProgressPanel } from '@/components/plugins/PluginInstallProgressPanel';
import { PluginConsentDialog, type ConsentMode } from '@/components/plugins/PluginConsentDialog';
import { capabilitiesExceedingConsent } from '@/lib/pluginCapabilities';

const CONTRIBUTION_TYPE_FILTERS = ['all', 'sensor', 'tool', 'channel'] as const;
type ContributionFilter = (typeof CONTRIBUTION_TYPE_FILTERS)[number];

/** Resolve the localized text from an i18n map, falling back to the default. */
function localized(
  base: string,
  i18nMap: Record<string, string> | undefined,
  lang: string,
): string {
  if (!i18nMap) return base;
  return i18nMap[lang] ?? i18nMap[lang.split('-')[0]] ?? base;
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
  const [registryEntries, setRegistryEntries] = useState<PluginRegistryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<ContributionFilter>('all');
  const [processingIds, setProcessingIds] = useState<Record<string, string>>({});
  const [installSnapshots, setInstallSnapshots] = useState<Record<string, PluginInstallJobSnapshot>>({});
  const [consent, setConsent] = useState<{
    mode: ConsentMode;
    name: string;
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

  const filteredEntries = useMemo(() => registryEntries.filter((entry) => {
    // Hide plugins that don't support the current platform.
    if (entry.platforms.length > 0 && !entry.platforms.includes(currentPlatform)) {
      return false;
    }
    // Category filter.
    if (typeFilter !== 'all' && !entry.contribution_types.includes(typeFilter)) {
      return false;
    }
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      entry.name.toLowerCase().includes(query) ||
      entry.plugin_id.toLowerCase().includes(query) ||
      entry.description.toLowerCase().includes(query) ||
      entry.author.toLowerCase().includes(query)
    );
  }), [registryEntries, currentPlatform, typeFilter, searchQuery]);

  const runInstall = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'installing' }));
    try {
      await pluginsApi.installFromRegistryWithProgress(pluginId, (snapshot) => {
        setInstallSnapshots((prev) => ({ ...prev, [pluginId]: snapshot }));
      });
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n[pluginId]; return n; });
    }
  };

  const handleInstall = (entry: PluginRegistryEntry) => {
    setConsent({
      mode: 'install',
      name: localized(entry.name, entry.name_i18n, i18n.language),
      version: entry.version,
      official: entry.official,
      capabilities: entry.capabilities ?? [],
      proceed: () => runInstall(entry.plugin_id),
    });
  };

  const handleUninstall = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'uninstalling' }));
    try {
      await pluginsApi.uninstall(pluginId);
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.uninstallSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      const message = err?.message || 'unknown';
      toast.error(t('settings.marketplace.feedback.uninstallFailed', { message }));
    } finally {
      setProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
  };

  const runUpdate = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'updating' }));
    try {
      await pluginsApi.updatePluginWithProgress(pluginId, (snapshot) => {
        setInstallSnapshots((prev) => ({ ...prev, [pluginId]: snapshot }));
      });
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.updateSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      toast.error(t('settings.marketplace.feedback.updateFailed', { message: err?.message || 'unknown' }));
    } finally {
      setProcessingIds((prev) => { const n = { ...prev }; delete n[pluginId]; return n; });
    }
  };

  const handleUpdate = (entry: PluginRegistryEntry) => {
    const installed = installedPlugins.find((p) => p.manifest.plugin_id === entry.plugin_id);
    const declared = entry.capabilities ?? [];
    const newCaps = capabilitiesExceedingConsent(declared, installed?.manifest.consented_capabilities ?? null);
    if (newCaps.length === 0) {
      void runUpdate(entry.plugin_id);
      return;
    }
    setConsent({
      mode: 'update',
      name: localized(entry.name, entry.name_i18n, i18n.language),
      version: entry.version,
      official: entry.official,
      capabilities: declared,
      newCapabilities: newCaps,
      proceed: () => runUpdate(entry.plugin_id),
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
      version: manifest.version,
      capabilities: manifest.capabilities ?? [],
      proceed: () => runUpload(file),
    });
  };

  return (
    <div className="space-y-5 pt-1">
      {/* Search + Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
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
            size="sm"
            onClick={() => void fetchRegistry({ force: true })}
            disabled={loading}
          >
            <RefreshCw className={loading ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
            {t('settings.marketplace.actions.refresh')}
          </Button>
        </div>
      </div>

      {/* Category filter */}
      <div className="flex flex-wrap gap-1.5">
        {CONTRIBUTION_TYPE_FILTERS.map((filter) => (
          <Button
            key={filter}
            type="button"
            variant={typeFilter === filter ? 'default' : 'outline'}
            size="sm"
            className="h-7 text-xs px-3"
            onClick={() => setTypeFilter(filter)}
          >
            {t(`settings.marketplace.filter.${filter}`)}
          </Button>
        ))}
      </div>

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
      ) : filteredEntries.length === 0 ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          {searchQuery
            ? t('settings.marketplace.noResults')
            : t('settings.marketplace.empty')}
        </div>
      ) : (
        <div className="grid gap-4">
          {filteredEntries.map((entry) => {
            const isInstalled = installedIds.has(entry.plugin_id) || entry.installed;
            const operation = processingIds[entry.plugin_id];
            const isProcessing = !!operation;

            return (
              <div
                key={entry.plugin_id}
                className="rounded-lg border border-[hsl(var(--settings-subnav-border)/0.72)] p-4 space-y-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">
                        {localized(entry.name, entry.name_i18n, i18n.language)}
                      </span>
                      <Badge variant="outline" className="text-xs">
                        v{entry.version}
                      </Badge>
                      {entry.official && (
                        <Badge variant="default" className="text-xs">
                          {t('settings.marketplace.badge.official')}
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {localized(entry.description, entry.description_i18n, i18n.language)}
                    </p>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      {entry.author && <span>{entry.author}</span>}
                      {entry.contribution_types.length > 0 && (
                        <div className="flex gap-1">
                          {entry.contribution_types.map((type) => (
                            <Badge key={type} variant="secondary" className="text-xs">
                              {t(`settings.marketplace.contributionType.${type}`, { defaultValue: type })}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {entry.homepage && (
                      <a
                        href={entry.homepage}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    )}

                    {isInstalled ? (
                      <div className="flex items-center gap-2">
                        {entry.update_available && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={isProcessing}
                            onClick={() => handleUpdate(entry)}
                          >
                            {operation === 'updating' ? (
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                              <RefreshCw className="mr-2 h-4 w-4" />
                            )}
                            {t('settings.marketplace.actions.update')}
                            {entry.installed_version && (
                              <span className="ml-1 text-xs text-muted-foreground">
                                {entry.installed_version} → {entry.version}
                              </span>
                            )}
                          </Button>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={isProcessing}
                          onClick={() => void handleUninstall(entry.plugin_id)}
                        >
                          {operation === 'uninstalling' ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="mr-2 h-4 w-4" />
                          )}
                          {t('settings.marketplace.actions.uninstall')}
                        </Button>
                        <Badge variant="secondary">
                          {t('settings.marketplace.badge.installed')}
                        </Badge>
                      </div>
                    ) : (
                      <Button
                        type="button"
                        variant="default"
                        size="sm"
                        disabled={isProcessing}
                        onClick={() => handleInstall(entry)}
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

                {installSnapshots[entry.plugin_id] ? (
                  <PluginInstallProgressPanel
                    snapshot={installSnapshots[entry.plugin_id]}
                    title={t('settings.marketplace.installProgress.itemTitle', {
                      name: localized(entry.name, entry.name_i18n, i18n.language),
                    })}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {consent && (
        <PluginConsentDialog
          open
          mode={consent.mode}
          pluginName={consent.name}
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
