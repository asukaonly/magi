import React, { useEffect, useState } from 'react';
import { AlertCircle, FolderTree, RefreshCw, ScrollText, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { timelineApi, type TimelineSourceStatusItem } from '@/api/modules/timeline';
import type { TimelineConfig, UserMode } from '@/api/modules/config';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';

interface TimelineSourcesSectionProps {
  value: TimelineConfig;
  userMode: UserMode;
  onChange: (updater: (draft: TimelineConfig) => void) => void;
}

type SourceName = keyof TimelineConfig['sources'];

const SOURCE_NAMES: SourceName[] = ['chat', 'manual_journal', 'browser_history', 'photo_library'];

const RETENTION_OPTIONS = [
  { value: 'analyze_only', labelKey: 'timeline.retention.analyzeOnly' },
  { value: 'retain_raw', labelKey: 'timeline.retention.retainRaw' },
];

const SYNC_MODE_OPTIONS = ['manual', 'interval', 'watch'];
const STORAGE_MODE_OPTIONS = ['managed', 'external_reference'];

export const TimelineSourcesSection: React.FC<TimelineSourcesSectionProps> = ({
  value,
  userMode,
  onChange,
}) => {
  const { t } = useTranslation('app');
  const [statuses, setStatuses] = useState<Record<string, TimelineSourceStatusItem>>({});
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);

  const expertMode = userMode === 'expert';

  useEffect(() => {
    const loadStatuses = async () => {
      setLoadingStatus(true);
      try {
        const response = await timelineApi.getSourceStatus();
        setStatuses(
          Object.fromEntries((response.sources || []).map((source) => [source.source_name, source]))
        );
      } catch (error: any) {
        toast.error(t('settings.timeline.errors.statusLoadFailed', { message: error?.message || 'unknown' }));
      } finally {
        setLoadingStatus(false);
      }
    };

    void loadStatuses();
  }, [t]);

  const updateSource = (
    sourceName: SourceName,
    updater: (draft: TimelineConfig['sources'][SourceName]) => void
  ) => {
    onChange((draft) => {
      updater(draft.sources[sourceName]);
    });
  };

  const handleSync = async (sourceName: SourceName) => {
    setSyncingSource(sourceName);
    try {
      await timelineApi.requestSync(sourceName);
      toast.success(t('settings.timeline.syncQueued', { source: t(`timeline.sources.${sourceName}`) }));
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.syncFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSyncingSource(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{t('settings.timeline.title')}</h2>
        <p className="text-sm text-muted-foreground">{t('settings.timeline.desc')}</p>
      </div>

      <Card className="border-border/50 bg-card/80 shadow-sm">
        <CardHeader>
          <CardTitle>{t('settings.timeline.overview.title')}</CardTitle>
          <CardDescription>{t('settings.timeline.overview.desc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="flex items-center justify-between rounded-2xl border border-border/40 bg-background/70 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.timelineEnabled')}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t('settings.timeline.fields.timelineEnabledHint')}</p>
              </div>
              <Switch
                checked={value.enabled}
                onCheckedChange={(checked) =>
                  onChange((draft) => {
                    draft.enabled = checked;
                  })
                }
                aria-label={t('settings.timeline.fields.timelineEnabled')}
              />
            </label>

            <label className="flex items-center justify-between rounded-2xl border border-border/40 bg-background/70 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.edgeOverride')}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t('settings.timeline.fields.edgeOverrideHint')}</p>
              </div>
              <Switch
                checked={value.expert_mode_edge_override}
                onCheckedChange={(checked) =>
                  onChange((draft) => {
                    draft.expert_mode_edge_override = checked;
                  })
                }
                disabled={!expertMode}
                aria-label={t('settings.timeline.fields.edgeOverride')}
              />
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            {SOURCE_NAMES.map((sourceName) => (
              <Badge key={sourceName} variant="secondary" className="rounded-full px-3 py-1">
                {t(`timeline.sources.${sourceName}`)} ·{' '}
                {value.sources[sourceName].enabled
                  ? t('settings.timeline.statuses.enabled')
                  : t('settings.timeline.statuses.disabled')}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4">
        {SOURCE_NAMES.map((sourceName) => {
          const source = value.sources[sourceName];
          const status = statuses[sourceName];
          const showFetchToggle = sourceName === 'browser_history';

          return (
            <Card
              key={sourceName}
              className="border-border/50 bg-card/80 shadow-sm"
              data-testid={`timeline-source-${sourceName}`}
            >
              <CardHeader className="pb-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <ScrollText className="h-4 w-4 text-primary" />
                      {t(`timeline.sources.${sourceName}`)}
                    </CardTitle>
                    <CardDescription className="mt-1">{t(`settings.timeline.sourceDesc.${sourceName}`)}</CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={status?.last_error ? 'destructive' : 'secondary'}>
                      {status?.last_error
                        ? t('settings.timeline.statuses.attention')
                        : t('settings.timeline.statuses.healthy')}
                    </Badge>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void handleSync(sourceName)}
                      disabled={syncingSource === sourceName}
                      aria-label={t('settings.timeline.actions.syncNow')}
                    >
                      <RefreshCw className={syncingSource === sourceName ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
                      {t('settings.timeline.actions.syncNow')}
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="flex items-center justify-between rounded-2xl border border-border/40 bg-background/70 px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.enabled')}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{t('settings.timeline.fields.enabledHint')}</p>
                    </div>
                    <Switch
                      checked={source.enabled}
                      onCheckedChange={(checked) => updateSource(sourceName, (draft) => {
                        draft.enabled = checked;
                      })}
                      aria-label={t('settings.timeline.fields.enabled')}
                    />
                  </label>

                  <div className="rounded-2xl border border-border/40 bg-background/70 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <ShieldCheck className="h-4 w-4 text-primary" />
                      {t('settings.timeline.fields.status')}
                    </div>
                    <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                      {loadingStatus ? (
                        <p>{t('settings.timeline.statuses.loading')}</p>
                      ) : status?.last_error ? (
                        <p className="text-destructive">{status.last_error}</p>
                      ) : (
                        <p>{t('settings.timeline.statuses.ready')}</p>
                      )}
                      {status?.last_success && <p>{status.last_success}</p>}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2" htmlFor={`${sourceName}-retention-mode`}>
                    <span className="text-sm font-medium text-foreground">{t('settings.timeline.fields.retentionMode')}</span>
                    <select
                      id={`${sourceName}-retention-mode`}
                      className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm"
                      aria-label={t('settings.timeline.fields.retentionMode')}
                      value={source.default_retention_mode}
                      onChange={(event) => updateSource(sourceName, (draft) => {
                        draft.default_retention_mode = event.target.value as TimelineConfig['sources'][SourceName]['default_retention_mode'];
                      })}
                    >
                      {RETENTION_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {t(option.labelKey)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="space-y-2" htmlFor={`${sourceName}-sync-interval`}>
                    <span className="text-sm font-medium text-foreground">{t('settings.timeline.fields.syncInterval')}</span>
                    <Input
                      id={`${sourceName}-sync-interval`}
                      type="number"
                      min={1}
                      aria-label={t('settings.timeline.fields.syncInterval')}
                      value={source.sync_interval_minutes}
                      onChange={(event) => updateSource(sourceName, (draft) => {
                        draft.sync_interval_minutes = Number(event.target.value) || 1;
                      })}
                    />
                  </label>

                  <label className="space-y-2" htmlFor={`${sourceName}-sync-mode`}>
                    <span className="text-sm font-medium text-foreground">{t('settings.timeline.fields.syncMode')}</span>
                    <select
                      id={`${sourceName}-sync-mode`}
                      className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm"
                      value={source.sync_mode}
                      onChange={(event) => updateSource(sourceName, (draft) => {
                        draft.sync_mode = event.target.value as TimelineConfig['sources'][SourceName]['sync_mode'];
                      })}
                    >
                      {SYNC_MODE_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {t(`settings.timeline.syncModes.${option}`)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="space-y-2" htmlFor={`${sourceName}-storage-mode`}>
                    <span className="text-sm font-medium text-foreground">{t('settings.timeline.fields.storageMode')}</span>
                    <select
                      id={`${sourceName}-storage-mode`}
                      className="h-10 w-full rounded-xl border border-input bg-background px-3 text-sm"
                      value={source.storage_mode}
                      onChange={(event) => updateSource(sourceName, (draft) => {
                        draft.storage_mode = event.target.value as TimelineConfig['sources'][SourceName]['storage_mode'];
                      })}
                    >
                      {STORAGE_MODE_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {t(`settings.timeline.storageModes.${option}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                {showFetchToggle && (
                  <label className="flex items-center justify-between rounded-2xl border border-border/40 bg-background/70 px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.fetchPageContent')}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{t('settings.timeline.fields.fetchPageContentHint')}</p>
                    </div>
                    <Switch
                      checked={source.fetch_page_content}
                      onCheckedChange={(checked) => updateSource(sourceName, (draft) => {
                        draft.fetch_page_content = checked;
                      })}
                      aria-label={t('settings.timeline.fields.fetchPageContent')}
                    />
                  </label>
                )}

                {expertMode && (
                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="space-y-2" htmlFor={`${sourceName}-source-path`}>
                      <span className="inline-flex items-center gap-2 text-sm font-medium text-foreground">
                        <FolderTree className="h-4 w-4 text-primary" />
                        {t('settings.timeline.fields.sourcePath')}
                      </span>
                      <Input
                        id={`${sourceName}-source-path`}
                        aria-label={t('settings.timeline.fields.sourcePath')}
                        value={source.source_path || status?.source_path || ''}
                        onChange={(event) => updateSource(sourceName, (draft) => {
                          draft.source_path = event.target.value;
                        })}
                        placeholder={t('settings.timeline.fields.sourcePathPlaceholder')}
                      />
                    </label>

                    <label className="space-y-2" htmlFor={`${sourceName}-edge-whitelist`}>
                      <span className="inline-flex items-center gap-2 text-sm font-medium text-foreground">
                        <AlertCircle className="h-4 w-4 text-primary" />
                        {t('settings.timeline.fields.edgeWhitelist')}
                      </span>
                      <Input
                        id={`${sourceName}-edge-whitelist`}
                        aria-label={t('settings.timeline.fields.edgeWhitelist')}
                        value={source.edge_whitelist.join(', ')}
                        onChange={(event) => updateSource(sourceName, (draft) => {
                          draft.edge_whitelist = event.target.value
                            .split(',')
                            .map((item) => item.trim())
                            .filter(Boolean);
                        })}
                        placeholder={t('settings.timeline.fields.edgeWhitelistPlaceholder')}
                      />
                    </label>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
};

export default TimelineSourcesSection;
