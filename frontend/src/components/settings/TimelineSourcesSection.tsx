import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { pluginsApi, type ActivationFlowSpec } from '@/api/modules/plugins';
import type { TimelineConfig, UserMode } from '@/api/modules/config';
import { timelineApi, type TimelineSourceStatusItem } from '@/api/modules/timeline';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
const SOURCE_ENABLED_SUFFIX = '.enabled';

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

const getSourceEnabledKey = (source: TimelineSourceStatusItem) =>
  source.fields.find((field) => field.key.endsWith(SOURCE_ENABLED_SUFFIX))?.key ??
  `sensors.${source.source_name}.enabled`;

const buildActivationValues = (flow: ActivationFlowSpec, source: TimelineSourceStatusItem) =>
  Object.fromEntries(
    flow.fields.map((field) => [field.key, source.current_settings[field.key] ?? field.default])
  );

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

const joinSourceMeta = (source: TimelineSourceStatusItem) =>
  [source.sync_mode, `${source.sync_interval_minutes}m`, source.default_retention_mode].filter(Boolean).join(' · ');

const SourceRow: React.FC<{
  source: TimelineSourceStatusItem;
  onClick: () => void;
}> = ({ source, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    data-testid={`timeline-source-launch-${source.source_name}`}
    className="grid w-full gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/30 sm:grid-cols-[minmax(0,1.2fr)_auto_auto]"
  >
    <div className="min-w-0">
      <div className="flex items-center gap-3">
        <span className="truncate text-sm font-medium text-foreground">{source.display_name}</span>
        {source.last_error ? <span className="h-2 w-2 rounded-full bg-destructive" aria-hidden="true" /> : null}
      </div>
      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{source.description}</p>
    </div>
    <div className="text-xs text-muted-foreground sm:text-right">
      <div>{joinSourceMeta(source)}</div>
      <div className="mt-1">{source.last_error || formatTimestamp(source.last_sync_at) || '—'}</div>
    </div>
    <div className="sm:justify-self-end">
      <Badge variant={source.enabled ? 'default' : 'secondary'} className="rounded-full">
        {source.enabled ? 'ON' : 'OFF'}
      </Badge>
    </div>
  </button>
);

const StatusMetric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="space-y-1">
    <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
    <div className="text-sm text-foreground">{value}</div>
  </div>
);

const SectionBlock: React.FC<{
  title: string;
  description?: string;
  children: React.ReactNode;
}> = ({ title, description, children }) => (
  <section className="space-y-4 border-t border-border/60 pt-6">
    <div className="space-y-1">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {description ? <p className="max-w-3xl text-sm text-muted-foreground">{description}</p> : null}
    </div>
    {children}
  </section>
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
  const [queuedSource, setQueuedSource] = useState<{
    sourceName: string;
    lastRunAt: number | string | null | undefined;
    lastSyncAt: number | string | null | undefined;
  } | null>(null);
  const [activationDialog, setActivationDialog] = useState<{
    source: TimelineSourceStatusItem;
    flow: ActivationFlowSpec;
    values: Record<string, any>;
    saving: boolean;
    intent: 'enable' | 'sync';
  } | null>(null);
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
    const pullSources = statuses.filter((source) => source.supports_pull_sync).length;
    return `${statuses.length} · ${activeSources} · ${pullSources}`;
  }, [statuses]);

  const flushPluginUpdates = async (pluginId: string, immediateUpdates: Record<string, any> = {}) => {
    if (saveTimersRef.current[pluginId]) {
      window.clearTimeout(saveTimersRef.current[pluginId]);
      delete saveTimersRef.current[pluginId];
    }
    const queued = pendingUpdatesRef.current[pluginId] || {};
    const updates = { ...queued, ...immediateUpdates };
    pendingUpdatesRef.current[pluginId] = {};
    if (Object.keys(updates).length === 0) {
      return;
    }
    await pluginsApi.updateSettings(pluginId, updates);
    await onRefreshSources();
  };

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
        await flushPluginUpdates(source.plugin_id);
      } catch (error: any) {
        toast.error(t('settings.timeline.errors.settingsSaveFailed', { message: error?.message || 'unknown' }));
      }
    }, 400);
  };

  const handleSourceEnabledChange = async (source: TimelineSourceStatusItem, checked: boolean) => {
    const enabledKey = getSourceEnabledKey(source);
    if (!checked) {
      queueSave(source, enabledKey, false);
      return;
    }
    const flow = source.activation_flow ?? null;
    if (source.activation_required && flow) {
      setActivationDialog({
        source,
        flow,
        values: buildActivationValues(flow, source),
        saving: false,
        intent: 'enable',
      });
      return;
    }
    try {
      setDrafts((prev) => ({
        ...prev,
        [source.source_name]: {
          ...(prev[source.source_name] || {}),
          [enabledKey]: true,
        },
      }));
      await flushPluginUpdates(source.plugin_id, { [enabledKey]: true });
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.settingsSaveFailed', { message: error?.message || 'unknown' }));
    }
  };

  const confirmActivationFlow = async () => {
    if (!activationDialog) {
      return;
    }
    const { source, flow, values } = activationDialog;
    setActivationDialog((prev) => (prev ? { ...prev, saving: true } : prev));
    try {
      await flushPluginUpdates(source.plugin_id, {
        ...values,
        [flow.enabled_key]: true,
        [flow.configured_key]: true,
      });
      setDrafts((prev) => ({
        ...prev,
        [source.source_name]: {
          ...(prev[source.source_name] || {}),
          ...values,
          [flow.enabled_key]: true,
        },
      }));
      if (activationDialog.intent === 'sync') {
        await performSync(source, { suppressQueuedToast: true });
      }
      toast.success(t('settings.timeline.activation.enabled', { source: source.display_name }));
      setActivationDialog(null);
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.activationFailed', { message: error?.message || 'unknown' }));
      setActivationDialog((prev) => (prev ? { ...prev, saving: false } : prev));
    }
  };

  const performSync = async (
    source: TimelineSourceStatusItem,
    options: { suppressQueuedToast?: boolean } = {}
  ) => {
    setSyncingSource(source.source_name);
    setQueuedSource({
      sourceName: source.source_name,
      lastRunAt: source.last_run_at,
      lastSyncAt: source.last_sync_at,
    });
    try {
      await timelineApi.requestSync(source.source_name);
      if (!options.suppressQueuedToast) {
        toast.success(t('settings.timeline.syncQueued', { source: source.display_name }));
      }
      await onRefreshSources();
    } catch (error: any) {
      setQueuedSource(null);
      toast.error(t('settings.timeline.errors.syncFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSyncingSource(null);
    }
  };

  const handleSync = async (source: TimelineSourceStatusItem) => {
    const flow = source.activation_flow ?? null;
    if (source.activation_required && flow) {
      setActivationDialog({
        source,
        flow,
        values: buildActivationValues(flow, source),
        saving: false,
        intent: 'sync',
      });
      return;
    }
    await performSync(source);
  };

  useEffect(() => {
    if (!queuedSource) {
      return;
    }
    const source = statuses.find((item) => item.source_name === queuedSource.sourceName);
    if (!source) {
      setQueuedSource(null);
      return;
    }
    const runAdvanced = source.last_run_at !== queuedSource.lastRunAt;
    const syncAdvanced = source.last_sync_at !== queuedSource.lastSyncAt;
    if (source.running || runAdvanced || syncAdvanced || source.last_error) {
      setQueuedSource(null);
    }
  }, [queuedSource, statuses]);

  const getSyncActivityValue = (source: TimelineSourceStatusItem) => {
    if (syncingSource === source.source_name || source.running) {
      return t('settings.timeline.statuses.syncing');
    }
    if (queuedSource?.sourceName === source.source_name) {
      return t('settings.timeline.statuses.queued');
    }
    if (source.activation_required) {
      return t('settings.timeline.statuses.awaitingSetup');
    }
    if (source.last_error) {
      return t('settings.timeline.statuses.attention');
    }
    return t('settings.timeline.statuses.idle');
  };

  if (!selectedSource) {
    return (
      <div className="mx-auto max-w-5xl space-y-8" data-testid="timeline-overview">
        <header className="space-y-5 border-b border-border/60 pb-6">
          <div className="space-y-2">
            <h2 className="text-xl font-semibold text-foreground">{t('settings.timeline.title')}</h2>
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{t('settings.timeline.workspace.desc')}</p>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/70 px-4 py-3">
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

            <label className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/70 px-4 py-3">
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
        </header>

        <SectionBlock
          title={t('settings.timeline.workspace.directoryTitle')}
          description={t('settings.timeline.workspace.directoryDesc')}
        >
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t('settings.timeline.workspace.metricsSummary', { summary })}</span>
            <Button type="button" variant="ghost" size="sm" onClick={() => void onRefreshSources()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('settings.timeline.actions.refresh')}
            </Button>
          </div>

          <div className="overflow-hidden rounded-2xl border border-border/60 bg-background/75">
            {loadingStatus ? (
              <div className="px-4 py-8 text-sm text-muted-foreground">{t('settings.timeline.statuses.loading')}</div>
            ) : statuses.length === 0 ? (
              <div className="px-4 py-8 text-sm text-muted-foreground">{t('settings.timeline.workspace.empty')}</div>
            ) : (
              <div className="divide-y divide-border/60">
                {statuses.map((source) => (
                  <SourceRow key={source.source_name} source={source} onClick={() => onSelectSource(source.source_name)} />
                ))}
              </div>
            )}
          </div>
        </SectionBlock>
      </div>
    );
  }

  const sourceEnabledKey = getSourceEnabledKey(selectedSource);
  const sourceEnabled =
    drafts[selectedSource.source_name]?.[sourceEnabledKey] ??
    selectedSource.current_settings[sourceEnabledKey] ??
    selectedSource.enabled;
  const detailFields = selectedSource.fields.filter((field) => {
    if (field.key === sourceEnabledKey) {
      return false;
    }
    return expertMode || !isExpertOnlyField(field.key);
  });

  return (
    <div className="mx-auto max-w-5xl space-y-8" data-testid={`timeline-source-detail-${selectedSource.source_name}`}>
      <header className="space-y-5 border-b border-border/60 pb-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => onSelectSource(null)}
            className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            {t('settings.timeline.workspace.backToOverview')}
          </button>

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => void onRefreshSources()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('settings.timeline.actions.refresh')}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleSync(selectedSource)}
              disabled={!selectedSource.supports_pull_sync || syncingSource === selectedSource.source_name}
            >
              <RefreshCw className={cn('mr-2 h-4 w-4', syncingSource === selectedSource.source_name && 'animate-spin')} />
              {t('settings.timeline.actions.syncNow')}
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={sourceEnabled ? 'default' : 'secondary'} className="rounded-full">
              {sourceEnabled ? t('settings.timeline.statuses.enabled') : t('settings.timeline.statuses.disabled')}
            </Badge>
            {selectedSource.last_error ? (
              <Badge variant="destructive" className="rounded-full">
                {t('settings.timeline.statuses.attention')}
              </Badge>
            ) : (
              <Badge variant="secondary" className="rounded-full">
                {t('settings.timeline.statuses.healthy')}
              </Badge>
            )}
            <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{selectedSource.plugin_id}</span>
          </div>
          <h2 className="text-3xl font-semibold tracking-tight text-foreground">{selectedSource.display_name}</h2>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            {selectedSource.description || t(`settings.timeline.sourceDesc.${selectedSource.source_name}`)}
          </p>
        </div>

        <div className="grid gap-3 rounded-2xl border border-border/60 bg-background/70 px-4 py-4 md:grid-cols-[minmax(0,1.3fr)_auto_auto] md:items-center">
          <div className="space-y-1">
            <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.enabled')}</p>
            <p className="text-xs text-muted-foreground">
              {selectedSource.last_error || t('settings.timeline.workspace.sourceStateHint', { mode: joinSourceMeta(selectedSource) })}
            </p>
          </div>
          <div className="text-sm text-muted-foreground">
            {t('settings.timeline.workspace.lastSyncInline', {
              time: formatTimestamp(selectedSource.last_sync_at) || '—',
            })}
          </div>
          <div className="flex items-center gap-3 md:justify-self-end">
            <Switch
              checked={Boolean(sourceEnabled)}
              onCheckedChange={(checked) => void handleSourceEnabledChange(selectedSource, checked)}
              aria-label={t('settings.timeline.fields.enabled')}
            />
          </div>
        </div>
      </header>

      <SectionBlock
        title={t('settings.timeline.workspace.sourceStatusTitle')}
        description={t('settings.timeline.workspace.sourceStatusDesc')}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusMetric
            label={t('settings.timeline.fields.status')}
            value={loadingStatus ? t('settings.timeline.statuses.loading') : getSyncActivityValue(selectedSource)}
          />
          <StatusMetric
            label={t('settings.timeline.workspace.lastRun')}
            value={formatTimestamp(selectedSource.last_run_at) || '—'}
          />
          <StatusMetric
            label={t('settings.timeline.workspace.lastSyncLabel')}
            value={formatTimestamp(selectedSource.last_sync_at) || '—'}
          />
          <StatusMetric
            label={t('settings.timeline.workspace.lastBatch')}
            value={String(selectedSource.last_raw_result_count || selectedSource.last_result_count || 0)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span>{t('settings.timeline.workspace.nextRunInline', { time: formatTimestamp(selectedSource.next_run_at) || '—' })}</span>
          <span>{t('settings.timeline.workspace.pullSupportInline', { status: selectedSource.supports_pull_sync
            ? t('settings.timeline.workspace.available')
            : t('settings.timeline.workspace.notAvailable') })}</span>
          {selectedSource.last_error ? (
            <span className="text-destructive">{selectedSource.last_error}</span>
          ) : null}
        </div>
      </SectionBlock>

      <SectionBlock
        title={t('settings.timeline.workspace.configurationTitle')}
        description={t('settings.timeline.workspace.configurationDesc')}
      >
        <PluginSettingsFields
          fields={detailFields}
          values={drafts[selectedSource.source_name] || selectedSource.current_settings}
          onChange={(key, nextValue) => queueSave(selectedSource, key, nextValue)}
        />
      </SectionBlock>

      <Dialog open={Boolean(activationDialog)} onOpenChange={(open) => !open && setActivationDialog(null)}>
        <DialogContent className="max-w-lg">
          {activationDialog ? (
            <>
              <DialogHeader>
                <DialogTitle>{activationDialog.flow.title}</DialogTitle>
                <DialogDescription>{activationDialog.flow.description}</DialogDescription>
              </DialogHeader>

              <div className="px-6 pb-6">
                <PluginSettingsFields
                  fields={activationDialog.flow.fields}
                  values={activationDialog.values}
                  onChange={(key, value) =>
                    setActivationDialog((prev) =>
                      prev
                        ? {
                            ...prev,
                            values: {
                              ...prev.values,
                              [key]: value,
                            },
                          }
                        : prev
                    )
                  }
                  disabled={activationDialog.saving}
                />
              </div>

              <DialogFooter>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setActivationDialog(null)}
                  disabled={activationDialog.saving}
                >
                  {activationDialog.flow.cancel_label}
                </Button>
                <Button type="button" onClick={() => void confirmActivationFlow()} disabled={activationDialog.saving}>
                  {activationDialog.flow.confirm_label}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default TimelineSourcesSection;
