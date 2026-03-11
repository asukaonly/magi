import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  BadgeCheck,
  Compass,
  Orbit,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  Waypoints,
} from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { pluginsApi } from '@/api/modules/plugins';
import type { TimelineConfig, UserMode } from '@/api/modules/config';
import { timelineApi, type TimelineSourceStatusItem } from '@/api/modules/timeline';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

interface TimelineSourcesSectionProps {
  value: TimelineConfig;
  userMode: UserMode;
  statuses: TimelineSourceStatusItem[];
  loadingStatus: boolean;
  selectedSourceName: string | null;
  onSelectSource: (sourceName: string | null) => void;
  onRefreshSources: () => Promise<void>;
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

const isExpertOnlyField = (key: string) => EXPERT_ONLY_SUFFIXES.some((suffix) => key.endsWith(suffix));

const formatTimestamp = (value: number | string | null | undefined) => {
  if (value == null || value === '') {
    return null;
  }
  const normalized = typeof value === 'number' ? value * 1000 : Date.parse(value);
  if (!Number.isFinite(normalized)) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(normalized));
};

const SourcePill: React.FC<{ source: TimelineSourceStatusItem; active: boolean; onClick: () => void }> = ({
  source,
  active,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    data-testid={`timeline-source-launch-${source.source_name}`}
    className={cn(
      'group flex w-full items-center justify-between rounded-2xl border px-4 py-4 text-left transition-all',
      active
        ? 'border-primary/50 bg-primary/10 shadow-[0_18px_40px_-28px_rgba(245,97,32,0.6)]'
        : 'border-border/60 bg-background/80 hover:border-primary/30 hover:bg-background'
    )}
  >
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-foreground">{source.display_name}</span>
        <Badge variant={source.enabled ? 'default' : 'secondary'} className="rounded-full">
          {source.enabled ? 'ON' : 'OFF'}
        </Badge>
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{source.description}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <span>{source.sync_mode}</span>
        <span>{source.sync_interval_minutes}m</span>
        <span>{source.default_retention_mode}</span>
      </div>
    </div>
    <div className="ml-4 shrink-0">
      {source.last_error ? (
        <ShieldAlert className="h-4 w-4 text-destructive" />
      ) : (
        <BadgeCheck className="h-4 w-4 text-primary transition-transform group-hover:translate-x-0.5" />
      )}
    </div>
  </button>
);

export const TimelineSourcesSection: React.FC<TimelineSourcesSectionProps> = ({
  value,
  userMode,
  statuses,
  loadingStatus,
  selectedSourceName,
  onSelectSource,
  onRefreshSources,
  onChange,
}) => {
  const { t } = useTranslation('app');
  const [drafts, setDrafts] = useState<Record<string, Record<string, any>>>({});
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const saveTimersRef = useRef<Record<string, number>>({});
  const pendingUpdatesRef = useRef<Record<string, Record<string, any>>>({});
  const expertMode = userMode === 'expert';

  useEffect(() => {
    setDrafts(buildDrafts(statuses));
  }, [statuses]);

  useEffect(
    () => () => {
      Object.values(saveTimersRef.current).forEach((timer) => window.clearTimeout(timer));
    },
    []
  );

  const selectedSource = useMemo(
    () => statuses.find((source) => source.source_name === selectedSourceName) ?? null,
    [selectedSourceName, statuses]
  );

  const summary = useMemo(() => {
    const activeSources = statuses.filter((source) => source.enabled).length;
    const healthySources = statuses.filter((source) => !source.last_error).length;
    const pullSources = statuses.filter((source) => source.supports_pull_sync).length;
    return {
      total: statuses.length,
      active: activeSources,
      healthy: healthySources,
      pull: pullSources,
    };
  }, [statuses]);

  const queueSave = (source: TimelineSourceStatusItem, key: string, nextValue: any) => {
    setDrafts((prev) => ({
      ...prev,
      [source.source_name]: {
        ...(prev[source.source_name] || {}),
        [key]: nextValue,
      },
    }));
    pendingUpdatesRef.current[source.plugin_id] = {
      ...(pendingUpdatesRef.current[source.plugin_id] || {}),
      [key]: nextValue,
    };

    if (saveTimersRef.current[source.plugin_id]) {
      window.clearTimeout(saveTimersRef.current[source.plugin_id]);
    }

    saveTimersRef.current[source.plugin_id] = window.setTimeout(async () => {
      try {
        const updates = pendingUpdatesRef.current[source.plugin_id] || {};
        pendingUpdatesRef.current[source.plugin_id] = {};
        await pluginsApi.updateSettings(source.plugin_id, updates);
        await onRefreshSources();
      } catch (error: any) {
        toast.error(t('settings.timeline.errors.settingsSaveFailed', { message: error?.message || 'unknown' }));
      }
    }, 400);
  };

  const handleSync = async (source: TimelineSourceStatusItem) => {
    setSyncingSource(source.source_name);
    try {
      await timelineApi.requestSync(source.source_name);
      toast.success(t('settings.timeline.syncQueued', { source: source.display_name }));
      await onRefreshSources();
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.syncFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSyncingSource(null);
    }
  };

  if (!selectedSource) {
    return (
      <div className="space-y-8" data-testid="timeline-overview">
        <section className="overflow-hidden rounded-[32px] border border-border/60 bg-[linear-gradient(135deg,rgba(245,97,32,0.12),rgba(245,97,32,0.02)_36%,rgba(255,255,255,0)_100%)] px-7 py-7">
          <div className="grid gap-6 xl:grid-cols-[1.35fr_0.9fr]">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-background/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-primary">
                <Orbit className="h-3.5 w-3.5" />
                {t('settings.timeline.workspace.eyebrow')}
              </div>
              <div className="space-y-2">
                <h2 className="font-serif text-[clamp(1.8rem,2vw,2.7rem)] font-semibold tracking-[-0.04em] text-foreground">
                  {t('settings.timeline.title')}
                </h2>
                <p className="max-w-3xl text-sm leading-7 text-muted-foreground">{t('settings.timeline.workspace.desc')}</p>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-2xl border border-border/60 bg-background/85 px-4 py-4">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {t('settings.timeline.workspace.metrics.total')}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">{summary.total}</p>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/85 px-4 py-4">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {t('settings.timeline.workspace.metrics.active')}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">{summary.active}</p>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/85 px-4 py-4">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                    {t('settings.timeline.workspace.metrics.pull')}
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">{summary.pull}</p>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-border/60 bg-background/85 p-5">
              <div className="mb-4 flex items-center gap-2">
                <Compass className="h-4 w-4 text-primary" />
                <p className="text-sm font-semibold text-foreground">{t('settings.timeline.overview.title')}</p>
              </div>
              <div className="space-y-3">
                <label className="flex items-center justify-between rounded-2xl border border-border/50 bg-muted/20 px-4 py-3">
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
                <label className="flex items-center justify-between rounded-2xl border border-border/50 bg-muted/20 px-4 py-3">
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
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <Card className="border-border/60 bg-card/80 shadow-sm">
            <CardHeader>
              <CardTitle>{t('settings.timeline.workspace.directoryTitle')}</CardTitle>
              <CardDescription>{t('settings.timeline.workspace.directoryDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {loadingStatus ? (
                <div className="rounded-2xl border border-dashed border-border/60 px-4 py-8 text-sm text-muted-foreground">
                  {t('settings.timeline.statuses.loading')}
                </div>
              ) : statuses.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-border/60 px-4 py-8 text-sm text-muted-foreground">
                  {t('settings.timeline.workspace.empty')}
                </div>
              ) : (
                statuses.map((source) => (
                  <SourcePill
                    key={source.source_name}
                    source={source}
                    active={false}
                    onClick={() => onSelectSource(source.source_name)}
                  />
                ))
              )}
            </CardContent>
          </Card>

          <Card className="border-border/60 bg-card/80 shadow-sm">
            <CardHeader>
              <CardTitle>{t('settings.timeline.workspace.healthTitle')}</CardTitle>
              <CardDescription>{t('settings.timeline.workspace.healthDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {statuses.map((source) => (
                <div
                  key={source.source_name}
                  className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">{source.display_name}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {source.last_error
                          ? source.last_error
                          : source.last_sync_at
                            ? t('settings.timeline.workspace.lastSync', { time: formatTimestamp(source.last_sync_at) })
                            : t('settings.timeline.statuses.ready')}
                      </p>
                    </div>
                    <Badge variant={source.last_error ? 'destructive' : 'secondary'}>
                      {source.last_error
                        ? t('settings.timeline.statuses.attention')
                        : t('settings.timeline.statuses.healthy')}
                    </Badge>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>
      </div>
    );
  }

  const detailFields = selectedSource.fields.filter((field) => expertMode || !isExpertOnlyField(field.key));

  return (
    <div className="space-y-8" data-testid={`timeline-source-detail-${selectedSource.source_name}`}>
      <section className="overflow-hidden rounded-[32px] border border-border/60 bg-[linear-gradient(140deg,rgba(245,97,32,0.14),rgba(245,97,32,0.02)_38%,rgba(255,255,255,0)_100%)] px-7 py-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-4">
            <button
              type="button"
              onClick={() => onSelectSource(null)}
              className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/80 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              {t('settings.timeline.workspace.backToOverview')}
            </button>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={selectedSource.enabled ? 'default' : 'secondary'} className="rounded-full px-3 py-1">
                  {selectedSource.enabled
                    ? t('settings.timeline.statuses.enabled')
                    : t('settings.timeline.statuses.disabled')}
                </Badge>
                <Badge variant={selectedSource.last_error ? 'destructive' : 'secondary'} className="rounded-full px-3 py-1">
                  {selectedSource.last_error
                    ? t('settings.timeline.statuses.attention')
                    : t('settings.timeline.statuses.healthy')}
                </Badge>
                <Badge variant="outline" className="rounded-full px-3 py-1">
                  {selectedSource.plugin_id}
                </Badge>
              </div>
              <h2 className="font-serif text-[clamp(1.8rem,2vw,2.6rem)] font-semibold tracking-[-0.04em] text-foreground">
                {selectedSource.display_name}
              </h2>
              <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
                {selectedSource.description || t(`settings.timeline.sourceDesc.${selectedSource.source_name}`)}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" onClick={() => void onRefreshSources()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('settings.timeline.actions.refresh')}
            </Button>
            <Button
              type="button"
              onClick={() => void handleSync(selectedSource)}
              disabled={!selectedSource.supports_pull_sync || syncingSource === selectedSource.source_name}
            >
              <RefreshCw className={cn('mr-2 h-4 w-4', syncingSource === selectedSource.source_name && 'animate-spin')} />
              {t('settings.timeline.actions.syncNow')}
            </Button>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card className="border-border/60 bg-card/80 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Waypoints className="h-4 w-4 text-primary" />
              {t('settings.timeline.workspace.sourceStatusTitle')}
            </CardTitle>
            <CardDescription>{t('settings.timeline.workspace.sourceStatusDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4">
              <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                {t('settings.timeline.fields.status')}
              </p>
              <p className="mt-2 text-sm text-foreground">
                {loadingStatus
                  ? t('settings.timeline.statuses.loading')
                  : selectedSource.last_error || t('settings.timeline.statuses.ready')}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4">
                <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  {t('settings.timeline.workspace.nextRun')}
                </p>
                <p className="mt-2 text-sm text-foreground">{formatTimestamp(selectedSource.next_run_at) || '—'}</p>
              </div>
              <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4">
                <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  {t('settings.timeline.workspace.lastSyncLabel')}
                </p>
                <p className="mt-2 text-sm text-foreground">{formatTimestamp(selectedSource.last_sync_at) || '—'}</p>
              </div>
              <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4">
                <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  {t('settings.timeline.workspace.triggerMode')}
                </p>
                <p className="mt-2 text-sm text-foreground">
                  {selectedSource.sync_mode} · {selectedSource.sync_interval_minutes}m
                </p>
              </div>
              <div className="rounded-2xl border border-border/50 bg-background/80 px-4 py-4">
                <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  {t('settings.timeline.workspace.pullSupport')}
                </p>
                <p className="mt-2 text-sm text-foreground">
                  {selectedSource.supports_pull_sync
                    ? t('settings.timeline.workspace.available')
                    : t('settings.timeline.workspace.notAvailable')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/60 bg-card/80 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ScrollText className="h-4 w-4 text-primary" />
              {t('settings.timeline.workspace.configurationTitle')}
            </CardTitle>
            <CardDescription>{t('settings.timeline.workspace.configurationDesc')}</CardDescription>
          </CardHeader>
          <CardContent>
            <PluginSettingsFields
              fields={detailFields}
              values={drafts[selectedSource.source_name] || selectedSource.current_settings}
              onChange={(key, nextValue) => queueSave(selectedSource, key, nextValue)}
            />
          </CardContent>
        </Card>
      </section>
    </div>
  );
};

export default TimelineSourcesSection;
