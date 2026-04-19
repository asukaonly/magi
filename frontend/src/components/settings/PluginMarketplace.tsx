import React, { useCallback, useEffect, useState } from 'react';
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
  type PluginPackageState,
  type PluginRegistryEntry,
} from '@/api/modules/plugins';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface PluginMarketplaceProps {
  installedPlugins: PluginPackageState[];
  onInstallComplete: () => Promise<void>;
}

export const PluginMarketplace: React.FC<PluginMarketplaceProps> = ({
  installedPlugins,
  onInstallComplete,
}) => {
  const { t } = useTranslation('app');
  const [registryEntries, setRegistryEntries] = useState<PluginRegistryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [processingIds, setProcessingIds] = useState<Record<string, string>>({});

  const fetchRegistry = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await pluginsApi.getRegistry();
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

  const filteredEntries = registryEntries.filter((entry) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      entry.name.toLowerCase().includes(query) ||
      entry.plugin_id.toLowerCase().includes(query) ||
      entry.description.toLowerCase().includes(query) ||
      entry.author.toLowerCase().includes(query)
    );
  });

  const handleInstall = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'installing' }));
    try {
      await pluginsApi.installFromRegistry(pluginId);
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      const message = err?.message || 'unknown';
      toast.error(t('settings.marketplace.feedback.installFailed', { message }));
    } finally {
      setProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
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

  const handleUpdate = async (pluginId: string) => {
    setProcessingIds((prev) => ({ ...prev, [pluginId]: 'updating' }));
    try {
      await pluginsApi.updatePlugin(pluginId);
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.updateSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      const message = err?.message || 'unknown';
      toast.error(t('settings.marketplace.feedback.updateFailed', { message }));
    } finally {
      setProcessingIds((prev) => {
        const next = { ...prev };
        delete next[pluginId];
        return next;
      });
    }
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setProcessingIds((prev) => ({ ...prev, __upload: 'uploading' }));
    try {
      await pluginsApi.installFromUpload(file);
      await onInstallComplete();
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      await fetchRegistry();
    } catch (err: any) {
      const message = err?.message || 'unknown';
      toast.error(t('settings.marketplace.feedback.installFailed', { message }));
    } finally {
      setProcessingIds((prev) => {
        const next = { ...prev };
        delete next.__upload;
        return next;
      });
      event.target.value = '';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
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
            onClick={() => void fetchRegistry()}
            disabled={loading}
          >
            <RefreshCw className={loading ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
            {t('settings.marketplace.actions.refresh')}
          </Button>
        </div>
      </div>

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
          <Button type="button" variant="outline" size="sm" onClick={() => void fetchRegistry()}>
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
                        {entry.name}
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
                      {entry.description}
                    </p>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      {entry.author && <span>{entry.author}</span>}
                      {entry.contribution_types.length > 0 && (
                        <div className="flex gap-1">
                          {entry.contribution_types.map((type) => (
                            <Badge key={type} variant="secondary" className="text-xs">
                              {type}
                            </Badge>
                          ))}
                        </div>
                      )}
                      {entry.platforms.length > 0 && (
                        <div className="flex gap-1">
                          {entry.platforms.map((platform) => (
                            <Badge key={platform} variant="outline" className="text-xs">
                              {platform}
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
                            onClick={() => void handleUpdate(entry.plugin_id)}
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
                        onClick={() => void handleInstall(entry.plugin_id)}
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
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default PluginMarketplace;
