import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import type { ActivationFlowSpec } from '@/api/modules/plugins';
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
  pluginDrafts: Record<string, Record<string, any>>;
  onSelectSource: (sourceName: string | null) => void;
  onRefreshSources: () => Promise<void>;
  onChange: (updater: (draft: TimelineConfig) => void) => void;
  onPluginFieldChange: (pluginId: string, key: string, value: any) => void;
  onPluginFieldsChange: (pluginId: string, updates: Record<string, any>) => void;
}

const EXPERT_ONLY_SUFFIXES = ['source_path', 'edge_whitelist'];
const SOURCE_ENABLED_SUFFIX = '.enabled';

const isExpertOnlyField = (key: string) => EXPERT_ONLY_SUFFIXES.some((suffix) => key.endsWith(suffix));

const getSourceEnabledKey = (source: TimelineSourceStatusItem) =>
  source.fields.find((field) => field.key.endsWith(SOURCE_ENABLED_SUFFIX))?.key ??
  `sensors.${source.source_name}.enabled`;

const buildActivationValues = (
  flow: ActivationFlowSpec,
  source: TimelineSourceStatusItem,
  pluginDrafts: Record<string, Record<string, any>>
) =>
  Object.fromEntries(
    flow.fields.map((field) => [
      field.key,
      pluginDrafts[source.plugin_id]?.[field.key] ?? source.current_settings[field.key] ?? field.default,
    ])
  );

const buildActivationResetValues = (flow: ActivationFlowSpec) =>
  Object.fromEntries(flow.fields.map((field) => [field.key, field.default]));

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
    hour12: false,
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
    className="grid w-full gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] px-0 py-4 text-left transition-colors last:border-b-0 hover:bg-transparent sm:grid-cols-[minmax(0,1.2fr)_auto_auto]"
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
      <Badge variant={source.enabled ? 'default' : 'secondary'} className="rounded-md">
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
  <section className="space-y-4 pt-4">
    <div className="space-y-1">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {description ? <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{description}</p> : null}
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
  pluginDrafts,
  onSelectSource,
  onRefreshSources,
  onChange,
  onPluginFieldChange,
  onPluginFieldsChange,
}) => {
  const { t } = useTranslation('app');
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
    intent: 'enable';
  } | null>(null);
  const expertMode = userMode === 'expert';

  const selectedSource = useMemo(
    () => statuses.find((source) => source.source_name === selectedSourceName) ?? null,
    [selectedSourceName, statuses]
  );

  const summary = useMemo(() => {
    const activeSources = statuses.filter((source) => source.enabled).length;
    const pullSources = statuses.filter((source) => source.supports_pull_sync).length;
    return `${statuses.length} · ${activeSources} · ${pullSources}`;
  }, [statuses]);

  const resolveSourceValue = (source: TimelineSourceStatusItem, key: string, fallback?: any) =>
    pluginDrafts[source.plugin_id]?.[key] ?? source.current_settings[key] ?? fallback;

  const handleSourceEnabledChange = (source: TimelineSourceStatusItem, checked: boolean) => {
    const enabledKey = getSourceEnabledKey(source);
    if (!checked) {
      onPluginFieldChange(source.plugin_id, enabledKey, false);
      return;
    }
    const flow = source.activation_flow ?? null;
    if (source.activation_required && flow) {
      setActivationDialog({
        source,
        flow,
        values: buildActivationValues(flow, source, pluginDrafts),
        intent: 'enable',
      });
      return;
    }
    onPluginFieldChange(source.plugin_id, enabledKey, true);
  };

  const confirmActivationFlow = () => {
    if (!activationDialog) {
      return;
    }
    const { source, flow, values } = activationDialog;
    onPluginFieldsChange(source.plugin_id, {
      ...values,
      [flow.enabled_key]: true,
      [flow.configured_key]: true,
    });
    toast.success(t('settings.timeline.activation.enabled', { source: source.display_name }));
    setActivationDialog(null);
  };

  const performSync = async (source: TimelineSourceStatusItem) => {
    setSyncingSource(source.source_name);
    setQueuedSource({
      sourceName: source.source_name,
      lastRunAt: source.last_run_at,
      lastSyncAt: source.last_sync_at,
    });
    try {
      await timelineApi.requestSync(source.source_name);
      toast.success(t('settings.timeline.syncQueued', { source: source.display_name }));
      await onRefreshSources();
    } catch (error: any) {
      setQueuedSource(null);
      toast.error(t('settings.timeline.errors.syncFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSyncingSource(null);
    }
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

  const getSyncActivityValue = (source: TimelineSourceStatusItem, activationRequired: boolean) => {
    if (syncingSource === source.source_name || source.running) {
      return t('settings.timeline.statuses.syncing');
    }
    if (queuedSource?.sourceName === source.source_name) {
      return t('settings.timeline.statuses.queued');
    }
    if (activationRequired) {
      return t('settings.timeline.statuses.awaitingSetup');
    }
    if (source.last_error) {
      return t('settings.timeline.statuses.attention');
    }
    return t('settings.timeline.statuses.idle');
  };

  const handleResetActivation = (source: TimelineSourceStatusItem) => {
    const flow = source.activation_flow ?? null;
    if (!flow) {
      return;
    }
    onPluginFieldsChange(source.plugin_id, {
      ...buildActivationResetValues(flow),
      [flow.enabled_key]: false,
      [flow.configured_key]: false,
    });
    toast.success(t('settings.timeline.activation.resetSuccess', { source: source.display_name }));
  };

  if (!selectedSource) {
    return (
      <div className="mx-auto max-w-5xl space-y-8" data-testid="timeline-overview">
        <header className="space-y-5">
          <div className="grid gap-6 border-t border-[hsl(var(--settings-subnav-border)/0.72)] pt-6 md:grid-cols-2">
            <label className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
              <div>
                <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.timelineEnabled')}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t('settings.timeline.fields.timelineEnabledHint')}</p>
              </div>
              <div className="flex justify-start sm:justify-end">
                <Switch
                  checked={value.enabled}
                  onCheckedChange={(checked) =>
                    onChange((draft) => {
                      draft.enabled = checked;
                    })
                  }
                  aria-label={t('settings.timeline.fields.timelineEnabled')}
                />
              </div>
            </label>

            <label className="grid gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
              <div>
                <p className="text-sm font-medium text-foreground">{t('settings.timeline.fields.edgeOverride')}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t('settings.timeline.fields.edgeOverrideHint')}</p>
              </div>
              <div className="flex justify-start sm:justify-end">
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
              </div>
            </label>
          </div>
        </header>

        <section className="space-y-4 pt-4">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{t('settings.timeline.workspace.metricsSummary', { summary })}</span>
            <Button type="button" variant="ghost" size="sm" onClick={() => void onRefreshSources()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              {t('settings.timeline.actions.refresh')}
            </Button>
          </div>

          <div>
            {loadingStatus ? (
              <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-8 text-sm text-muted-foreground">{t('settings.timeline.statuses.loading')}</div>
            ) : statuses.length === 0 ? (
              <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-8 text-sm text-muted-foreground">{t('settings.timeline.workspace.empty')}</div>
            ) : (
              <div>
                {statuses.map((source) => (
                  <SourceRow key={source.source_name} source={source} onClick={() => onSelectSource(source.source_name)} />
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    );
  }

  const sourceEnabledKey = getSourceEnabledKey(selectedSource);
  const sourceEnabled = Boolean(resolveSourceValue(selectedSource, sourceEnabledKey, selectedSource.enabled));
  const activationFlow = selectedSource.activation_flow ?? null;
  const activationConfigured = Boolean(
    activationFlow && resolveSourceValue(selectedSource, activationFlow.configured_key, false)
  );
  const activationRequired = Boolean(activationFlow && !sourceEnabled && !activationConfigured);
  const operationallyEnabled = selectedSource.enabled && sourceEnabled;
  const detailFields = selectedSource.fields.filter((field) => {
    if (field.key === sourceEnabledKey) {
      return false;
    }
    return expertMode || !isExpertOnlyField(field.key);
  });
  const detailValues = Object.fromEntries(
    detailFields.map((field) => [field.key, resolveSourceValue(selectedSource, field.key, field.default)])
  );

  return (
    <div className="mx-auto max-w-5xl space-y-8" data-testid={`timeline-source-detail-${selectedSource.source_name}`}>
      <header className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => onSelectSource(null)}
            className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            {t('settings.timeline.workspace.backToOverview')}
          </button>

          <div className="flex flex-wrap items-center gap-3">
            {activationFlow && activationConfigured ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => handleResetActivation(selectedSource)}
              >
                {t('settings.timeline.actions.resetActivation')}
              </Button>
            ) : null}
            {operationallyEnabled ? (
              <>
                <Button type="button" variant="outline" size="sm" onClick={() => void onRefreshSources()}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  {t('settings.timeline.actions.refresh')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void performSync(selectedSource)}
                  disabled={!selectedSource.supports_pull_sync || syncingSource === selectedSource.source_name}
                >
                  <RefreshCw
                    className={cn('mr-2 h-4 w-4', syncingSource === selectedSource.source_name && 'animate-spin')}
                  />
                  {t('settings.timeline.actions.syncNow')}
                </Button>
              </>
            ) : null}
            <label className="inline-flex items-center gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] px-0 py-1.5 text-sm text-foreground">
              <span>{t('settings.timeline.fields.enabled')}</span>
              <Switch
                checked={sourceEnabled}
                onCheckedChange={(checked) => handleSourceEnabledChange(selectedSource, checked)}
                aria-label={t('settings.timeline.fields.enabled')}
              />
            </label>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={sourceEnabled ? 'default' : 'secondary'} className="rounded-md">
              {sourceEnabled ? t('settings.timeline.statuses.enabled') : t('settings.timeline.statuses.disabled')}
            </Badge>
            {selectedSource.last_error ? (
              <Badge variant="destructive" className="rounded-md">
                {t('settings.timeline.statuses.attention')}
              </Badge>
            ) : (
              <Badge variant="secondary" className="rounded-md">
                {t('settings.timeline.statuses.healthy')}
              </Badge>
            )}
            <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{selectedSource.plugin_id}</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">{selectedSource.display_name}</h2>
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
            {selectedSource.description || t(`settings.timeline.sourceDesc.${selectedSource.source_name}`)}
          </p>
        </div>
        <div className="text-sm text-muted-foreground">{selectedSource.last_error || joinSourceMeta(selectedSource)}</div>
      </header>

      <SectionBlock title={t('settings.timeline.workspace.sourceStatusTitle')}>
        <div className="grid gap-5 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-3 md:grid-cols-2 xl:grid-cols-4">
          <StatusMetric
            label={t('settings.timeline.fields.status')}
            value={loadingStatus ? t('settings.timeline.statuses.loading') : getSyncActivityValue(selectedSource, activationRequired)}
          />
          <StatusMetric
            label={t('settings.timeline.workspace.lastRun')}
            value={formatTimestamp(selectedSource.last_run_at) || '—'}
          />
          <StatusMetric
            label={t('settings.timeline.workspace.nextRun')}
            value={formatTimestamp(selectedSource.next_run_at) || '—'}
          />
          <StatusMetric
            label={t('settings.timeline.workspace.lastBatch')}
            value={String(selectedSource.last_raw_result_count || selectedSource.last_result_count || 0)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span>
            {t('settings.timeline.workspace.pullSupportInline', {
              status: selectedSource.supports_pull_sync
                ? t('settings.timeline.workspace.available')
                : t('settings.timeline.workspace.notAvailable'),
            })}
          </span>
          {selectedSource.last_error ? <span className="text-destructive">{selectedSource.last_error}</span> : null}
        </div>
      </SectionBlock>

      <SectionBlock
        title={t('settings.timeline.workspace.configurationTitle')}
        description={t('settings.timeline.workspace.configurationDesc')}
      >
        <PluginSettingsFields
          fields={detailFields}
          values={detailValues}
          onChange={(key, nextValue) => onPluginFieldChange(selectedSource.plugin_id, key, nextValue)}
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
                  onChange={(key, nextValue) =>
                    setActivationDialog((prev) =>
                      prev
                        ? {
                            ...prev,
                            values: {
                              ...prev.values,
                              [key]: nextValue,
                            },
                          }
                        : prev
                    )
                  }
                />
              </div>

              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setActivationDialog(null)}>
                  {activationDialog.flow.cancel_label}
                </Button>
                <Button type="button" onClick={confirmActivationFlow}>
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
