import React, { useEffect, useMemo, useState } from 'react';
import { Download, History, Loader2, RefreshCw, ScrollText } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

import { pluginsApi, type ActivationFlowSpec, type PluginInstallJobSnapshot } from '@/api/modules/plugins';
import type { UserMode } from '@/api/modules/config';
import { sensorsApi, type SensorSourceStatusItem } from '@/api/modules/sensors';
import { PluginActivationDialog } from '@/components/plugins/PluginActivationDialog';
import { PluginConsentDialog } from '@/components/plugins/PluginConsentDialog';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { PluginInstallProgressPanel } from '@/components/plugins/PluginInstallProgressPanel';
import {
  SourceBackfillDialog,
  type SourceBackfillSelection,
} from '@/components/sources/SourceBackfillDialog';
import PluginSettingsCustomBlocks from '@/components/settings/PluginSettingsCustomBlocks';
import PluginSettingsActions from '@/components/settings/PluginSettingsActions';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import PluginSettingsTabs, {
  getActiveSettingsTab,
  isTabsSettingsLayout,
} from '@/components/settings/PluginSettingsTabs';
import { SettingsEmptyState } from '@/components/settings/SettingsSectionPrimitives';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import {
  buildTimelineCapabilities,
  getTimelineCapabilityDisplayName,
  getTimelineEntryDescription,
  getTimelineEntryDisplayName,
  type TimelineCapability,
  type TimelineAvailableEntry,
} from '@/utils/timeline-capabilities';
import { getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';

interface TimelineSourcesSectionProps {
  userMode: UserMode;
  statuses: SensorSourceStatusItem[];
  availableEntries?: TimelineAvailableEntry[];
  loadingStatus: boolean;
  selectedSourceName: string | null;
  pluginDrafts: Record<string, Record<string, any>>;
  onSelectSource: (sourceName: string | null) => void;
  onRefreshSources: () => Promise<void>;
  onPluginInstalled?: () => Promise<void>;
  onBrowseMarketplace?: () => void;
  onPluginFieldChange: (pluginId: string, key: string, value: any) => void;
  onPluginFieldsChange: (pluginId: string, updates: Record<string, any>) => void;
}

const EXPERT_ONLY_SUFFIXES = ['source_path', 'edge_whitelist'];
const SOURCE_ENABLED_SUFFIX = '.enabled';

const isExpertOnlyField = (key: string) => EXPERT_ONLY_SUFFIXES.some((suffix) => key.endsWith(suffix));

const getSourceEnabledKey = (source: SensorSourceStatusItem) =>
  source.fields.find((field) => field.key.endsWith(SOURCE_ENABLED_SUFFIX))?.key ??
  `sensors.${source.source_name}.enabled`;

const buildActivationValues = (
  flow: ActivationFlowSpec,
  source: SensorSourceStatusItem,
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

const SourceRow: React.FC<{
  capability: TimelineCapability;
  displayName: string;
  description: string;
  onClick: () => void;
}> = ({ capability, displayName, description, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    data-testid={`timeline-source-launch-${capability.id}`}
    className="grid w-full gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.6)] px-0 py-4 text-left transition-colors last:border-b-0 hover:bg-transparent sm:grid-cols-[minmax(0,1.2fr)_auto_auto]"
  >
    <div className="min-w-0">
      <div className="flex items-center gap-3">
        <span className="truncate text-sm font-medium text-foreground">{displayName}</span>
        {capability.attentionCount > 0 ? <span className="h-2 w-2 rounded-full bg-destructive" aria-hidden="true" /> : null}
      </div>
      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{description}</p>
    </div>
    <div className="text-xs text-muted-foreground sm:text-right">
      <div>{formatTimestamp(capability.lastSyncAt) || '—'}</div>
    </div>
    <div className="sm:justify-self-end">
      <Badge variant={capability.enabledCount > 0 ? 'default' : 'secondary'} className="rounded-md">
        {capability.enabledCount > 0 ? `${capability.enabledCount} ON` : 'OFF'}
      </Badge>
    </div>
  </button>
);

const EntryOption: React.FC<{
  source: SensorSourceStatusItem;
  selected: boolean;
  title: string;
  description: string;
  statusLabel: string;
  enabled: boolean;
  attention: boolean;
  onClick: () => void;
}> = ({ source, selected, title, description, statusLabel, enabled, attention, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    data-testid={`timeline-entry-option-${source.source_name}`}
    role="tab"
    aria-selected={selected}
    className={cn(
      'min-h-[104px] w-[280px] flex-none snap-start rounded-lg px-4 py-3 text-left transition-[background-color,box-shadow,color] duration-200 md:w-[300px] xl:w-[320px]',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35',
      selected
        ? 'bg-[hsl(var(--settings-shell-elevated)/0.9)] shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.7),0_12px_26px_hsl(var(--foreground)/0.045)]'
        : 'bg-[hsl(var(--settings-shell)/0.32)] shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34)] hover:bg-[hsl(var(--settings-shell-elevated)/0.58)]'
    )}
  >
    <div className="flex h-full flex-col justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{title}</span>
          {attention ? (
            <span className="h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden="true" />
          ) : null}
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
      <div className="flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
        <span>{source.last_error || formatTimestamp(source.last_sync_at) || '—'}</span>
        <Badge
          variant={attention ? 'destructive' : enabled ? 'default' : 'secondary'}
          className="shrink-0 rounded-md"
        >
          {statusLabel}
        </Badge>
      </div>
    </div>
  </button>
);

const AvailableEntryOption: React.FC<{
  entry: TimelineAvailableEntry;
  installing: boolean;
  statusLabel: string;
  installLabel: string;
  installingLabel: string;
  onInstall: () => void;
}> = ({ entry, installing, statusLabel, installLabel, installingLabel, onInstall }) => (
  <div
    data-testid={`timeline-marketplace-entry-${entry.pluginId}`}
    className="min-h-[112px] w-[280px] flex-none snap-start rounded-lg bg-[hsl(var(--settings-shell)/0.32)] px-4 py-3 text-left shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34)] md:w-[300px] xl:w-[320px]"
  >
    <div className="flex h-full flex-col justify-between gap-3">
      <div className="flex min-w-0 gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--settings-shell-elevated)/0.76)] shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.4)]">
          <PluginIcon
            iconId={entry.icon}
            pluginId={entry.pluginId}
            sourceName={entry.entryDisplayName}
            className="h-5 w-5"
          />
        </div>
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-foreground">{entry.entryDisplayName}</span>
            <Badge variant="secondary" className="shrink-0 rounded-md">
              v{entry.version}
            </Badge>
          </div>
          <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">{entry.entryDescription}</p>
        </div>
      </div>
      <div className="flex items-center justify-between gap-3">
        <Badge variant="outline" className="rounded-md">{statusLabel}</Badge>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 px-3"
          disabled={installing}
          onClick={onInstall}
        >
          {installing ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Download className="mr-2 h-4 w-4" />
          )}
          <span>{installing ? installingLabel : installLabel}</span>
        </Button>
      </div>
    </div>
  </div>
);

const StatusMetric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="space-y-1">
    <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
    <div className="text-sm text-foreground">{value}</div>
  </div>
);

const SectionBlock: React.FC<{
  title?: string;
  description?: string;
  children: React.ReactNode;
}> = ({ title, description, children }) => (
  <section className="space-y-4">
    {title || description ? (
      <div className="space-y-1">
        {title ? <h3 className="text-sm font-semibold text-foreground">{title}</h3> : null}
        {description ? <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{description}</p> : null}
      </div>
    ) : null}
    {children}
  </section>
);

export const TimelineSourcesSection: React.FC<TimelineSourcesSectionProps> = ({
  userMode,
  statuses,
  availableEntries = [],
  loadingStatus,
  selectedSourceName,
  pluginDrafts,
  onSelectSource,
  onRefreshSources,
  onPluginInstalled,
  onBrowseMarketplace,
  onPluginFieldChange,
  onPluginFieldsChange,
}) => {
  const { t } = useTranslation('app');
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [backfillingSource, setBackfillingSource] = useState<string | null>(null);
  const [backfillDialogSource, setBackfillDialogSource] = useState<SensorSourceStatusItem | null>(null);
  const [flushingSource, setFlushingSource] = useState<string | null>(null);
  const [installingEntryId, setInstallingEntryId] = useState<string | null>(null);
  const [installingEntryLabel, setInstallingEntryLabel] = useState<string | null>(null);
  const [installSnapshot, setInstallSnapshot] = useState<PluginInstallJobSnapshot | null>(null);
  const [installConsentEntry, setInstallConsentEntry] = useState<TimelineAvailableEntry | null>(null);
  const [selectedEntryName, setSelectedEntryName] = useState<string | null>(null);
  const [queuedSource, setQueuedSource] = useState<{
    sourceName: string;
    lastRunAt: number | string | null | undefined;
    lastSyncAt: number | string | null | undefined;
  } | null>(null);
  const [activationDialog, setActivationDialog] = useState<{
    source: SensorSourceStatusItem;
    flow: ActivationFlowSpec;
    values: Record<string, any>;
    intent: 'enable';
  } | null>(null);
  const expertMode = userMode === 'expert';

  const capabilities = useMemo(
    () => buildTimelineCapabilities(t, statuses),
    [t, statuses]
  );
  const selectedCapability = useMemo(
    () => capabilities.find((capability) => capability.id === selectedSourceName) ?? null,
    [capabilities, selectedSourceName]
  );
  const getDefaultEntry = (capability: TimelineCapability | null) => {
    if (!capability?.sources.length) {
      return null;
    }
    return (
      capability.sources.find((source) => source.last_error || source.available === false)
      ?? capability.sources.find((source) => source.enabled)
      ?? capability.sources[0]
    );
  };
  const selectedSource = useMemo(() => {
    const sources = selectedCapability?.sources ?? [];
    return (
      sources.find((source) => source.source_name === selectedEntryName)
      ?? getDefaultEntry(selectedCapability)
    );
  }, [selectedCapability, selectedEntryName]);

  useEffect(() => {
    const nextEntry = getDefaultEntry(selectedCapability);
    if (!selectedCapability || !nextEntry) {
      if (selectedEntryName !== null) {
        setSelectedEntryName(null);
      }
      return;
    }
    if (!selectedCapability.sources.some((source) => source.source_name === selectedEntryName)) {
      setSelectedEntryName(nextEntry.source_name);
    }
  }, [selectedCapability, selectedEntryName]);

  const resolveSourceValue = (source: SensorSourceStatusItem, key: string, fallback?: any) =>
    pluginDrafts[source.plugin_id]?.[key] ?? source.current_settings[key] ?? fallback;
  const getSourceDisplayName = (source: SensorSourceStatusItem) => getTimelineSourceDisplayName(t, source);

  const handleSourceEnabledChange = (source: SensorSourceStatusItem, checked: boolean) => {
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

  const confirmActivationFlow = async (values: Record<string, any>) => {
    if (!activationDialog) {
      return;
    }
    const { source, flow } = activationDialog;
    if (flow.authorize_on_confirm) {
      try {
        const result = await sensorsApi.requestAuthorization(source.source_name, values);
        if (!result.authorized) {
          toast.error(
            t('settings.timeline.errors.authorizationFailed', {
              message: result.message || 'authorization_denied',
            })
          );
          return;
        }
      } catch (error: any) {
        toast.error(t('settings.timeline.errors.authorizationFailed', { message: error?.message || 'unknown' }));
        return;
      }
    }
    onPluginFieldsChange(source.plugin_id, {
      ...values,
      [flow.enabled_key]: true,
      [flow.configured_key]: true,
    });
    toast.success(t('settings.timeline.activation.enabled', { source: getSourceDisplayName(source) }));
    setActivationDialog(null);
  };

  const performSync = async (source: SensorSourceStatusItem) => {
    setSyncingSource(source.source_name);
    setQueuedSource({
      sourceName: source.source_name,
      lastRunAt: source.last_run_at,
      lastSyncAt: source.last_sync_at,
    });
    try {
      await sensorsApi.requestSync(source.source_name);
      toast.success(t('settings.timeline.syncQueued', { source: getSourceDisplayName(source) }));
      await onRefreshSources();
    } catch (error: any) {
      setQueuedSource(null);
      toast.error(t('settings.timeline.errors.syncFailed', { message: error?.message || 'unknown' }));
    } finally {
      setSyncingSource(null);
    }
  };

  const performBackfill = async (source: SensorSourceStatusItem, selection: SourceBackfillSelection) => {
    setBackfillingSource(source.source_name);
    try {
      await sensorsApi.requestSync(source.source_name, {
        mode: 'backfill',
        backfillScope: selection.scope,
        backfillStartDate: selection.startDate,
        backfillEndDate: selection.endDate,
      });
      toast.success(t('settings.timeline.backfillQueued', { source: getSourceDisplayName(source) }));
      setBackfillDialogSource(null);
      await onRefreshSources();
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.backfillFailed', { message: error?.message || 'unknown' }));
    } finally {
      setBackfillingSource(null);
    }
  };

  const performStateFlush = async (source: SensorSourceStatusItem) => {
    setFlushingSource(source.source_name);
    try {
      await sensorsApi.requestStateFlush(source.source_name);
      toast.success(t('settings.timeline.stateFlushQueued', { source: getSourceDisplayName(source) }));
      await onRefreshSources();
    } catch (error: any) {
      toast.error(t('settings.timeline.errors.stateFlushFailed', { message: error?.message || 'unknown' }));
    } finally {
      setFlushingSource(null);
    }
  };

  const performAvailableEntryInstall = async (entry: TimelineAvailableEntry) => {
    setInstallingEntryId(entry.pluginId);
    setInstallingEntryLabel(entry.entryDisplayName);
    setInstallSnapshot(null);
    try {
      await pluginsApi.installFromRegistryWithProgress(entry.pluginId, setInstallSnapshot);
      toast.success(t('settings.marketplace.feedback.installSuccess'));
      if (onPluginInstalled) {
        await onPluginInstalled();
      } else {
        await onRefreshSources();
      }
    } catch (error: any) {
      toast.error(t('settings.marketplace.feedback.installFailed', { message: error?.message || 'unknown' }));
    } finally {
      setInstallingEntryId(null);
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

  const getSyncActivityValue = (source: SensorSourceStatusItem, activationRequired: boolean) => {
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

  const handleResetActivation = (source: SensorSourceStatusItem) => {
    const flow = source.activation_flow ?? null;
    if (!flow) {
      return;
    }
    onPluginFieldsChange(source.plugin_id, {
      ...buildActivationResetValues(flow),
      [flow.enabled_key]: false,
      [flow.configured_key]: false,
    });
    toast.success(t('settings.timeline.activation.resetSuccess', { source: getSourceDisplayName(source) }));
  };

  if (!selectedSource) {
    return (
      <div className="w-full space-y-6" data-testid="timeline-overview">
        <section>
          <div>
            {loadingStatus ? (
              <div className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-8 text-sm text-muted-foreground">{t('settings.timeline.statuses.loading')}</div>
            ) : capabilities.length === 0 ? (
              <SettingsEmptyState
                testId="settings-empty-state-timeline-sources"
                icon={ScrollText}
                title={t('settings.timeline.workspace.emptyTitle')}
                description={t('settings.timeline.workspace.emptyDescription')}
                actionLabel={t('settings.timeline.workspace.emptyAction')}
                onAction={onBrowseMarketplace}
              />
            ) : (
              <div>
                {capabilities.map((capability) => (
                  <SourceRow
                    key={capability.id}
                    capability={capability}
                    displayName={capability.displayName}
                    description={capability.description}
                    onClick={() => onSelectSource(capability.id)}
                  />
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
  const nextRunValue =
    selectedSource.sync_mode === 'manual'
      ? t('settings.timeline.workspace.manualTrigger')
      : formatTimestamp(selectedSource.next_run_at) || '—';
  const detailFields = selectedSource.fields.filter((field) => {
    if (field.key === sourceEnabledKey) {
      return false;
    }
    return expertMode || !isExpertOnlyField(field.key);
  });
  const detailValues = {
    ...selectedSource.current_settings,
    ...(pluginDrafts[selectedSource.plugin_id] ?? {}),
    ...Object.fromEntries(
      detailFields.map((field) => [field.key, resolveSourceValue(selectedSource, field.key, field.default)])
    ),
  };
  const settingsLayout = isTabsSettingsLayout(selectedSource.settings_layout)
    ? selectedSource.settings_layout
    : null;
  const activeSettingsTab = getActiveSettingsTab(settingsLayout, detailValues);
  const activeSettingsTabUnavailable = activeSettingsTab?.available === false || selectedSource.available === false;
  const visibleDetailFields = settingsLayout
    ? detailFields.filter((field) => field.key !== settingsLayout.controller_key)
    : detailFields;
  const showPullSupportHint = !selectedSource.supports_pull_sync || Boolean(selectedSource.last_error);
  const capabilityDisplayName = selectedCapability?.displayName ?? getTimelineCapabilityDisplayName(t, selectedSource);
  const entryDisplayName = getTimelineEntryDisplayName(t, selectedSource);
  const entryDescription = getTimelineEntryDescription(t, selectedSource);
  const capabilityId = selectedCapability?.id ?? selectedSource.source_name;
  const entrySources = selectedCapability?.sources ?? [selectedSource];
  const availableCapabilityEntries = availableEntries.filter((entry) => entry.capabilityId === capabilityId);
  const hasMultipleEntries = entrySources.length > 1;
  const showEntrySelector = entrySources.length > 0;
  const knownEntryCount = entrySources.length + availableCapabilityEntries.length;
  const hasMultipleKnownEntries = knownEntryCount > 1;
  const getEntryEnabled = (source: SensorSourceStatusItem) =>
    Boolean(resolveSourceValue(source, getSourceEnabledKey(source), source.enabled));
  const getEntryAttention = (source: SensorSourceStatusItem) =>
    Boolean(source.last_error || source.available === false);
  const getEntryStatusLabel = (source: SensorSourceStatusItem) => {
    if (getEntryAttention(source)) {
      return t('settings.timeline.statuses.attention');
    }
    return getEntryEnabled(source)
      ? t('settings.timeline.statuses.enabled')
      : t('settings.timeline.statuses.disabled');
  };
  const unavailableReason = selectedSource.available === false
    ? (selectedSource.unavailable_reason_translated || selectedSource.unavailable_reason)
    : null;
  const sourceHeaderActions = (
    <div
      className="flex flex-wrap items-center justify-end gap-3"
      data-testid="timeline-source-header-actions"
    >
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
          {selectedSource.supports_state_flush ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void performStateFlush(selectedSource)}
              disabled={flushingSource === selectedSource.source_name}
            >
              <RefreshCw
                className={cn('mr-2 h-4 w-4', flushingSource === selectedSource.source_name && 'animate-spin')}
              />
              {t('settings.timeline.actions.flushStateNow')}
            </Button>
          ) : null}
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
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setBackfillDialogSource(selectedSource)}
            disabled={!selectedSource.supports_pull_sync || backfillingSource === selectedSource.source_name}
          >
            <History
              className={cn('mr-2 h-4 w-4', backfillingSource === selectedSource.source_name && 'animate-spin')}
            />
            {t('settings.timeline.actions.backfill')}
          </Button>
        </>
      ) : null}
      <label className="inline-flex items-center gap-3 text-sm text-foreground">
        <span>{t('settings.timeline.fields.enabled')}</span>
        <Switch
          checked={sourceEnabled}
          onCheckedChange={(checked) => handleSourceEnabledChange(selectedSource, checked)}
          aria-label={t('settings.timeline.fields.enabled')}
        />
      </label>
    </div>
  );

  return (
    <div className="w-full space-y-6" data-testid={`timeline-capability-detail-${capabilityId}`}>
      <div data-testid={`timeline-source-detail-${capabilityId}`} className="space-y-6">
        <header className="border-b border-[hsl(var(--settings-subnav-border)/0.6)] pb-5">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center gap-2" data-testid="timeline-source-header-status">
                <h2 className="text-xl font-semibold tracking-tight text-foreground">
                  {capabilityDisplayName}
                </h2>
                <Badge variant={(selectedCapability?.enabledCount ?? (sourceEnabled ? 1 : 0)) > 0 ? 'default' : 'secondary'} className="rounded-md">
                  {selectedCapability?.enabledCount ?? (sourceEnabled ? 1 : 0)} {t('settings.timeline.statuses.enabled')}
                </Badge>
                {(selectedCapability?.attentionCount ?? (selectedSource.last_error ? 1 : 0)) > 0 ? (
                  <Badge variant="destructive" className="rounded-md">
                    {t('settings.timeline.statuses.attention')}
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="rounded-md">
                    {t('settings.timeline.statuses.healthy')}
                  </Badge>
                )}
              </div>
              <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
                {hasMultipleKnownEntries ? (selectedCapability?.description ?? entryDescription) : entryDescription}
              </p>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted-foreground">
                <span>
                  {t('settings.timeline.workspace.entries')}
                  <span className="ml-2 font-medium text-foreground">{knownEntryCount}</span>
                </span>
                <span>
                  {t('settings.timeline.statuses.attention')}
                  <span className="ml-2 font-medium text-foreground">
                    {selectedCapability?.attentionCount ?? (selectedSource.last_error ? 1 : 0)}
                  </span>
                </span>
                <span>
                  {t('settings.timeline.workspace.lastRun')}
                  <span className="ml-2 font-medium text-foreground">
                    {formatTimestamp(selectedCapability?.lastSyncAt ?? selectedSource.last_sync_at) || '—'}
                  </span>
                </span>
              </div>
            </div>
            {!hasMultipleEntries ? sourceHeaderActions : null}
          </div>
        </header>

        {showEntrySelector ? (
          <section
            className="relative"
            data-testid={`timeline-entry-selector-${capabilityId}`}
          >
            {hasMultipleEntries ? (
              <div
                className="pointer-events-none absolute bottom-3 right-0 top-0 z-10 w-10 bg-gradient-to-l from-[hsl(var(--background))] to-transparent"
                aria-hidden="true"
              />
            ) : null}
            <div
              className={cn(
                'flex snap-x gap-3 overflow-x-auto px-1 pb-3 [scrollbar-width:thin]',
                hasMultipleEntries ? 'pr-10' : 'pr-1'
              )}
              data-testid={`timeline-entry-selector-scroll-${capabilityId}`}
              role="tablist"
              aria-label={capabilityDisplayName}
            >
              {entrySources.map((source) => (
                <EntryOption
                  key={source.source_name}
                  source={source}
                  selected={source.source_name === selectedSource.source_name}
                  title={getTimelineEntryDisplayName(t, source)}
                  description={getTimelineEntryDescription(t, source)}
                  statusLabel={getEntryStatusLabel(source)}
                  enabled={getEntryEnabled(source)}
                  attention={getEntryAttention(source)}
                  onClick={() => setSelectedEntryName(source.source_name)}
                />
              ))}
            </div>
          </section>
        ) : null}

        {availableCapabilityEntries.length > 0 ? (
          <section
            className="relative space-y-3"
            data-testid={`timeline-available-entry-selector-${capabilityId}`}
          >
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  {t('settings.timeline.workspace.availableEntriesTitle')}
                </h3>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('settings.timeline.workspace.availableEntriesDesc')}
                </p>
              </div>
              {onBrowseMarketplace ? (
                <Button type="button" variant="ghost" size="sm" onClick={onBrowseMarketplace}>
                  {t('settings.timeline.actions.browseMarketplace')}
                </Button>
              ) : null}
            </div>
            <div className="flex snap-x gap-3 overflow-x-auto px-1 pb-3 [scrollbar-width:thin]">
              {availableCapabilityEntries.map((entry) => (
                <AvailableEntryOption
                  key={entry.pluginId}
                  entry={entry}
                  installing={installingEntryId === entry.pluginId}
                  statusLabel={t('settings.timeline.statuses.notInstalled')}
                  installLabel={t('settings.timeline.actions.installEntry')}
                  installingLabel={t('settings.timeline.actions.installingEntry')}
                  onInstall={() => setInstallConsentEntry(entry)}
                />
              ))}
            </div>
            {installSnapshot ? (
              <PluginInstallProgressPanel
                snapshot={installSnapshot}
                title={t('settings.marketplace.installProgress.itemTitle', {
                  name: installingEntryLabel ?? '',
                })}
              />
            ) : null}
          </section>
        ) : null}

        <div>
          <section
            className="min-w-0 space-y-6"
            data-testid={`timeline-entry-detail-${selectedSource.source_name}`}
          >
            <div
              data-testid={
                selectedSource.source_name !== capabilityId
                  ? `timeline-source-detail-${selectedSource.source_name}`
                  : undefined
              }
              className="space-y-6"
            >
              {hasMultipleEntries ? (
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-xl font-semibold tracking-tight text-foreground">{entryDisplayName}</h3>
                      <Badge variant={sourceEnabled ? 'default' : 'secondary'} className="rounded-md">
                        {sourceEnabled ? t('settings.timeline.statuses.enabled') : t('settings.timeline.statuses.disabled')}
                      </Badge>
                      {selectedSource.last_error || selectedSource.available === false ? (
                        <Badge variant="destructive" className="rounded-md">
                          {t('settings.timeline.statuses.attention')}
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="rounded-md">
                          {t('settings.timeline.statuses.healthy')}
                        </Badge>
                      )}
                    </div>
                    <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{entryDescription}</p>
                  </div>
                  {sourceHeaderActions}
                </div>
              ) : null}

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
                    value={nextRunValue}
                  />
                  <StatusMetric
                    label={t('settings.timeline.workspace.lastBatch')}
                    value={String(selectedSource.last_raw_result_count || selectedSource.last_result_count || 0)}
                  />
                </div>
                {showPullSupportHint || unavailableReason ? (
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
                    {!selectedSource.supports_pull_sync ? (
                      <span>
                        {t('settings.timeline.workspace.pullSupportInline', {
                          status: t('settings.timeline.workspace.notAvailable'),
                        })}
                      </span>
                    ) : null}
                    {unavailableReason ? <span className="text-destructive">{unavailableReason}</span> : null}
                    {selectedSource.last_error ? <span className="text-destructive">{selectedSource.last_error}</span> : null}
                  </div>
                ) : null}
              </SectionBlock>

              <SectionBlock>
                <div className="space-y-5">
                  {settingsLayout ? (
                    <PluginSettingsTabs
                      layout={settingsLayout}
                      values={detailValues}
                      onChange={(key, nextValue) => onPluginFieldChange(selectedSource.plugin_id, key, nextValue)}
                    />
                  ) : null}
                  {!activeSettingsTabUnavailable ? (
                    <>
                      <PluginSettingsCustomBlocks
                        pluginId={selectedSource.plugin_id}
                        blocks={selectedSource.settings_ui_blocks ?? []}
                        values={detailValues}
                        onChange={(key, nextValue) => onPluginFieldChange(selectedSource.plugin_id, key, nextValue)}
                      />
                      <PluginSettingsFields
                        fields={visibleDetailFields}
                        values={detailValues}
                        onChange={(key, nextValue) => onPluginFieldChange(selectedSource.plugin_id, key, nextValue)}
                        pluginId={selectedSource.plugin_id}
                      />
                      <PluginSettingsActions
                        pluginId={selectedSource.plugin_id}
                        actions={selectedSource.settings_actions ?? []}
                        values={detailValues}
                        onSettingsUpdates={onPluginFieldsChange}
                        onActionSettled={onRefreshSources}
                      />
                    </>
                  ) : null}
                </div>
              </SectionBlock>
            </div>
          </section>
        </div>

        {activationDialog ? (
          <PluginActivationDialog
            open
            onClose={() => setActivationDialog(null)}
            flow={activationDialog.flow}
            initialValues={activationDialog.values}
            onConfirm={(values) => confirmActivationFlow(values)}
            pluginId={activationDialog.source.plugin_id}
          />
        ) : null}
        {backfillDialogSource ? (
          <SourceBackfillDialog
            open
            sourceLabel={getSourceDisplayName(backfillDialogSource)}
            isSubmitting={backfillingSource === backfillDialogSource.source_name}
            onOpenChange={(open) => {
              if (!open) {
                setBackfillDialogSource(null);
              }
            }}
            onConfirm={(scope) => void performBackfill(backfillDialogSource, scope)}
          />
        ) : null}
        {installConsentEntry ? (
          <PluginConsentDialog
            open
            mode="install"
            pluginName={installConsentEntry.entryDisplayName}
            pluginId={installConsentEntry.pluginId}
            pluginIcon={installConsentEntry.icon}
            version={installConsentEntry.version}
            official={installConsentEntry.official}
            capabilities={installConsentEntry.capabilities ?? []}
            onCancel={() => setInstallConsentEntry(null)}
            onConfirm={() => {
              const entry = installConsentEntry;
              setInstallConsentEntry(null);
              void performAvailableEntryInstall(entry);
            }}
          />
        ) : null}
      </div>
    </div>
  );
};

export default TimelineSourcesSection;
