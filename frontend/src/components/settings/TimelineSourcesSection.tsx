import React, { useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, ScrollText, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { pluginsApi } from '@/api/modules/plugins';
import { timelineApi, type TimelineSourceStatusItem } from '@/api/modules/timeline';
import type { TimelineConfig, UserMode } from '@/api/modules/config';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';

interface TimelineSourcesSectionProps {
  value: TimelineConfig;
  userMode: UserMode;
  onChange: (updater: (draft: TimelineConfig) => void) => void;
}

const EXPERT_ONLY_SUFFIXES = ['source_path', 'edge_whitelist'];

const buildDrafts = (sources: TimelineSourceStatusItem[]) =>
  Object.fromEntries(
    sources.map((source) => [
      source.source_name,
      source.fields.reduce<Record<string, any>>((acc, field) => {
        acc[field.key] = source.current_settings[field.key] ?? field.default;
        return acc;
      }, {}),
    ])
  );

const isExpertOnlyField = (key: string) =>
  EXPERT_ONLY_SUFFIXES.some((suffix) => key.endsWith(suffix));

export const TimelineSourcesSection: React.FC<TimelineSourcesSectionProps> = ({
  value,
  userMode,
  onChange,
}) => {
  const { t } = useTranslation('app');
  const [statuses, setStatuses] = useState<TimelineSourceStatusItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Record<string, any>>>({});
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const saveTimersRef = useRef<Record<string, number>>({});
  const pendingUpdatesRef = useRef<Record<string, Record<string, any>>>({});

  const expertMode = userMode === 'expert';

  const loadStatuses = async () => {
    setLoadingStatus(true);
    try {
      const response = await timelineApi.getSourceStatus();
      setStatuses(response.sources || []);
      setDrafts(buildDrafts(response.sources || []));
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.statusLoadFailed', { message: error?.message || 'unknown' }));
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    void loadStatuses();
  }, [t]);

  const sourceBadges = useMemo(
    () =>
      statuses.map((source) => ({
        source_name: source.source_name,
        display_name: source.display_name,
        enabled: Boolean(drafts[source.source_name]?.[`sensors.${source.source_name}.enabled`] ?? source.enabled),
      })),
    [drafts, statuses]
  );

  const handleSync = async (source: TimelineSourceStatusItem) => {
    setSyncingSource(source.source_name);
    try {
      await timelineApi.requestSync(source.source_name);
      toast.success(t('settings.timeline.syncQueued', { source: source.display_name }));
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.syncFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSyncingSource(null);
    }
  };

  const queueSave = (source: TimelineSourceStatusItem, key: string, value: any) => {
    setDrafts((prev) => ({
      ...prev,
      [source.source_name]: {
        ...(prev[source.source_name] || {}),
        [key]: value,
      },
    }));
    pendingUpdatesRef.current[source.plugin_id] = {
      ...(pendingUpdatesRef.current[source.plugin_id] || {}),
      [key]: value,
    };

    if (saveTimersRef.current[source.plugin_id]) {
      window.clearTimeout(saveTimersRef.current[source.plugin_id]);
    }

    saveTimersRef.current[source.plugin_id] = window.setTimeout(async () => {
      try {
        const updates = pendingUpdatesRef.current[source.plugin_id] || {};
        pendingUpdatesRef.current[source.plugin_id] = {};
        await pluginsApi.updateSettings(source.plugin_id, updates);
        await loadStatuses();
      } catch (error: any) {
        toast.error(t('settings.timeline.errors.settingsSaveFailed', { message: error?.message || 'unknown' }));
      }
    }, 400);
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
            {sourceBadges.map((source) => (
              <Badge key={source.source_name} variant="secondary" className="rounded-full px-3 py-1">
                {source.display_name} ·{' '}
                {source.enabled
                  ? t('settings.timeline.statuses.enabled')
                  : t('settings.timeline.statuses.disabled')}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4">
        {statuses.map((source) => {
          const fields = source.fields.filter((field) => expertMode || !isExpertOnlyField(field.key));
          return (
            <Card
              key={source.source_name}
              className="border-border/50 bg-card/80 shadow-sm"
              data-testid={`timeline-source-${source.source_name}`}
            >
              <CardHeader className="pb-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <ScrollText className="h-4 w-4 text-primary" />
                      {source.display_name}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {source.description || t(`settings.timeline.sourceDesc.${source.source_name}`)}
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={source.last_error ? 'destructive' : 'secondary'}>
                      {source.last_error
                        ? t('settings.timeline.statuses.attention')
                        : t('settings.timeline.statuses.healthy')}
                    </Badge>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void handleSync(source)}
                      disabled={syncingSource === source.source_name}
                      aria-label={t('settings.timeline.actions.syncNow')}
                    >
                      <RefreshCw className={syncingSource === source.source_name ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
                      {t('settings.timeline.actions.syncNow')}
                    </Button>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-5">
                <div className="rounded-2xl border border-border/40 bg-background/70 px-4 py-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    {t('settings.timeline.fields.status')}
                  </div>
                  <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                    {loadingStatus ? (
                      <p>{t('settings.timeline.statuses.loading')}</p>
                    ) : source.last_error ? (
                      <p className="text-destructive">{source.last_error}</p>
                    ) : (
                      <p>{t('settings.timeline.statuses.ready')}</p>
                    )}
                    <p>
                      {source.sync_mode} · {source.sync_interval_minutes}m · {source.default_retention_mode}
                    </p>
                    {source.last_success ? <p>{source.last_success}</p> : null}
                  </div>
                </div>

                <PluginSettingsFields
                  fields={fields}
                  values={drafts[source.source_name] || source.current_settings}
                  onChange={(key, nextValue) => queueSave(source, key, nextValue)}
                />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
};

export default TimelineSourcesSection;
