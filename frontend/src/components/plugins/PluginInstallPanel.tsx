import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { pluginsApi } from '@/api/modules/plugins';
import type { ExtensionFieldSpec, PluginCapability } from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

import { usePluginInstallPanelStore } from '../../stores/pluginInstallPanel';
import { usePluginInstallFlow, type InstallStepId } from '../../hooks/usePluginInstallFlow';
import { InstallStepper } from './InstallStepper';
import { PluginConsentDialog } from './PluginConsentDialog';
import { dispatchAppEvent } from '@/constants/events';
import { localizedPluginText } from '@/utils/plugin-display-groups';

/** "netease-music" → "Netease Music" — fallback when no name is provided. */
function humanizePluginId(pluginId: string): string {
  return pluginId
    .split(/[-_]/)
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

/**
 * Required-field gate, replicated from PluginActivationDialog.isFieldSatisfied
 * (not exported there). A field is satisfied when it is optional, or has a
 * non-empty value (strings trimmed; arrays non-empty; everything else defined).
 */
const isFieldSatisfied = (field: ExtensionFieldSpec, value: unknown): boolean => {
  if (!field.required) return true;
  if (value === undefined || value === null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return true;
};

/**
 * Seed the form state from each field's `default` (PluginSettingsFields does not
 * seed defaults itself — PluginActivationDialog does this via seedValues). Without
 * this, a field whose visibility depends on another field's default value never
 * appears, and the required-gate would read undefined for defaulted fields.
 */
const seedFieldValues = (
  fields: ExtensionFieldSpec[],
): Record<string, unknown> => {
  const seed: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.default !== undefined && field.default !== null) {
      seed[field.key] = field.default;
    }
  }
  return seed;
};

/**
 * The single, MainLayout-mounted modal that runs the honest plugin-connect flow.
 * Opened from shared product entry points via usePluginInstallPanelStore; drives the
 * usePluginInstallFlow state machine and renders, per phase:
 *   - awaiting_fields → the field form (reused PluginSettingsFields + required gate)
 *   - loading / running / done → the InstallStepper with dynamic labels
 *   - unsupported → an honest "can't one-click connect yet" message (no silent no-op)
 *   - error → the message + a retry action
 */
export function PluginInstallPanel(): JSX.Element | null {
  const { t, i18n } = useTranslation('onboarding');
  const open = usePluginInstallPanelStore((s) => s.open);
  const pluginId = usePluginInstallPanelStore((s) => s.pluginId);
  const pluginName = usePluginInstallPanelStore((s) => s.pluginName);
  const pluginIcon = usePluginInstallPanelStore((s) => s.pluginIcon);
  const installMode = usePluginInstallPanelStore((s) => s.installMode);
  const panelContext = usePluginInstallPanelStore((s) => s.context);
  const closePanel = usePluginInstallPanelStore((s) => s.closePanel);
  const onDone = usePluginInstallPanelStore((s) => s.onDone);
  const isFirstContext = panelContext === 'first_context';
  const isHistoryImport = panelContext === 'history_import';

  const [consented, setConsented] = useState(false);
  const [registryRefreshKey, setRegistryRefreshKey] = useState(0);
  const [registryState, setRegistryState] = useState<
    'loading' | 'ready' | 'not_found' | 'error'
  >('loading');
  const [entryMeta, setEntryMeta] = useState<{
    name: string;
    name_i18n: Record<string, string>;
    capabilities: PluginCapability[];
    executionMode?: "restricted_process" | "trusted_process";
    version: string;
    official: boolean;
    icon: string | null;
    installFingerprint: string | null;
  } | null>(null);

  const handleRegistryChanged = useCallback(() => {
    setConsented(false);
    setEntryMeta(null);
    setRegistryState('loading');
    setRegistryRefreshKey((value) => value + 1);
    toast.error(t('app:settings.marketplace.feedback.registryChanged'));
  }, [t]);

  // In install mode, hold the connect flow until the user accepts the plugin's
  // declared capabilities (mirrors the marketplace's consent dialog). The flow
  // stays idle while pluginId is null, so installs never run unseen.
  const flowActive = open && (
    !installMode
    || (consented && Boolean(entryMeta?.installFingerprint))
  );
  const flow = usePluginInstallFlow(
    flowActive ? pluginId : null,
    installMode,
    panelContext,
    entryMeta?.installFingerprint ?? null,
    handleRegistryChanged,
  );
  const [values, setValues] = useState<Record<string, unknown>>({});
  const doneFiredRef = useRef(false);

  // Reset the consent gate + fetched metadata whenever the panel closes.
  useEffect(() => {
    if (!open) {
      setConsented(false);
      setEntryMeta(null);
      setRegistryState('loading');
      setRegistryRefreshKey(0);
    }
  }, [open]);

  // Fetch the plugin's declared capabilities for the install-mode consent gate.
  useEffect(() => {
    if (!open || !installMode || !pluginId) return;
    let cancelled = false;
    setConsented(false);
    setEntryMeta(null);
    setRegistryState('loading');
    void pluginsApi
      .getRegistry(registryRefreshKey > 0 ? { force: true } : undefined)
      .then((reg) => {
        if (cancelled) return;
        const e = reg.plugins.find((p) => p.plugin_id === pluginId);
        if (!e) {
          setEntryMeta({
            name: humanizePluginId(pluginId),
            name_i18n: {},
            capabilities: [],
            version: '',
            official: false,
            icon: null,
            installFingerprint: null,
          });
          setRegistryState('not_found');
          return;
        }
        setEntryMeta({
          name: e.name,
          name_i18n: e.name_i18n ?? {},
          capabilities: e.capabilities ?? [],
          executionMode: e.execution_mode,
          version: e.version,
          official: e.official ?? false,
          icon: e.icon ?? null,
          installFingerprint: reg.install_fingerprint,
        });
        setRegistryState(reg.install_fingerprint ? 'ready' : 'error');
      })
      .catch(() => {
        if (!cancelled) {
          setEntryMeta({
            name: humanizePluginId(pluginId),
            name_i18n: {},
            capabilities: [],
            version: '',
            official: false,
            icon: null,
            installFingerprint: null,
          });
          setRegistryState('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, installMode, pluginId, registryRefreshKey]);

  // Fire the entry point's onDone exactly once when the flow succeeds (`done`).
  // Reset the guard when the panel closes so a later open can fire again.
  useEffect(() => {
    if (!open) {
      doneFiredRef.current = false;
      return;
    }
    if (flow.phase === 'done' && !doneFiredRef.current) {
      doneFiredRef.current = true;
      // The installed/connected plugin set just changed — let every suggestion
      // surface re-evaluate so this plugin stops being suggested.
      dispatchAppEvent.pluginsChanged();
      onDone?.({
        pluginId: pluginId ?? '',
        connectionId: flow.connectionId,
        sourceName: flow.sourceName ?? undefined,
        firstContextCount: isFirstContext
          ? flow.syncedCount ?? flow.memoryCount ?? flow.memoryTotalCount ?? null
          : undefined,
      });
    }
  }, [
    open,
    flow.phase,
    flow.connectionId,
    flow.memoryCount,
    flow.memoryTotalCount,
    flow.sourceName,
    flow.syncedCount,
    isFirstContext,
    onDone,
    pluginId,
  ]);

  const fieldSpecs = flow.flow?.fields ?? [];

  // Seed field defaults once the flow surfaces a field form; reset on close.
  useEffect(() => {
    if (!open) {
      setValues({});
      return;
    }
    if (flow.phase === 'awaiting_fields') {
      setValues(seedFieldValues(fieldSpecs));
    }
    // fieldSpecs identity is stable per flow fetch; key off phase + flow.flow.
  }, [open, flow.phase, flow.flow]);

  const handleFieldChange = useCallback((key: string, nextValue: unknown) => {
    setValues((prev) => ({ ...prev, [key]: nextValue }));
  }, []);

  const allRequiredSatisfied = useMemo(
    () => fieldSpecs.every((field) => isFieldSatisfied(field, values[field.key])),
    [fieldSpecs, values],
  );

  const name = pluginName || (
    entryMeta
      ? localizedPluginText(entryMeta.name, entryMeta.name_i18n, i18n.language)
      : pluginId
        ? humanizePluginId(pluginId)
        : ''
  );
  const icon = pluginIcon || entryMeta?.icon || '';
  const syncStep = flow.steps.find((step) => step.id === 'sync');
  const memoryStep = flow.steps.find((step) => step.id === 'memory');
  const memoryInputCount = flow.memoryTotalCount ?? flow.memoryCount;
  const memoryHasNoNewRecords = memoryStep?.status === 'done' && memoryInputCount === 0;
  const syncedRawCount = flow.syncedRawCount ?? 0;
  const rawRecordsRead = syncedRawCount > 0;

  const syncProgressDetail = useMemo(() => {
    if (flow.syncDeferred) {
      return t('pluginInstallPanel.syncBackground');
    }
    if (flow.syncedCount != null) {
      if (flow.syncedCount === 0) {
        return rawRecordsRead
          ? t('pluginInstallPanel.syncedRawOnly', { count: syncedRawCount })
          : t('pluginInstallPanel.syncedEmpty');
      }
      return t('pluginInstallPanel.syncedCount', { count: flow.syncedCount });
    }
    if (syncStep?.status === 'running') {
      return t('pluginInstallPanel.syncWaiting');
    }
    return undefined;
  }, [flow.syncDeferred, flow.syncedCount, rawRecordsRead, syncedRawCount, syncStep?.status, t]);

  const memoryProgressDetail = useMemo(() => {
    if (isFirstContext) {
      const count = flow.syncedCount ?? flow.memoryCount ?? flow.memoryTotalCount;
      if (count != null) {
        return count === 0
          ? t('pluginInstallPanel.firstContextEmpty')
          : t('pluginInstallPanel.firstContextPrepared', { count });
      }
      if (memoryStep?.status === 'running') {
        return t('pluginInstallPanel.firstContextChecking');
      }
      return undefined;
    }

    const processed = flow.memoryProcessedCount ?? (flow.memoryReady ? flow.memoryCount : null);
    const total = flow.memoryTotalCount ?? flow.syncedCount ?? flow.memoryCount;
    const remaining =
      flow.memoryRemainingCount ??
      (processed != null && total != null ? Math.max(0, total - processed) : null);
    const latestSyncCount = flow.syncedCount;
    const displayTotal =
      latestSyncCount != null && latestSyncCount > 0 && total != null && total > latestSyncCount
        ? latestSyncCount
        : total;
    const displayProcessed =
      processed != null && displayTotal != null ? Math.min(processed, displayTotal) : processed;
    const displayRemaining =
      displayProcessed != null && displayTotal != null
        ? Math.max(0, displayTotal - displayProcessed)
        : remaining;

    if (displayProcessed != null && displayTotal != null) {
      if (displayTotal === 0) {
        return rawRecordsRead
          ? t('pluginInstallPanel.memoryEmptyAfterRaw')
          : t('pluginInstallPanel.memoryEmpty');
      }
      return t('pluginInstallPanel.memoryProgress', {
        processed: displayProcessed,
        total: displayTotal,
        remaining: displayRemaining ?? Math.max(0, displayTotal - displayProcessed),
      });
    }
    if (displayProcessed != null) {
      return t('pluginInstallPanel.memoryProcessed', { count: displayProcessed });
    }
    if (displayTotal != null) {
      if (displayTotal === 0) {
        return rawRecordsRead
          ? t('pluginInstallPanel.memoryEmptyAfterRaw')
          : t('pluginInstallPanel.memoryEmpty');
      }
      return t('pluginInstallPanel.memoryTotal', { count: displayTotal });
    }
    if (memoryStep?.status === 'running') {
      return t('pluginInstallPanel.memoryChecking');
    }
    return undefined;
  }, [
    flow.memoryProcessedCount,
    flow.memoryReady,
    flow.memoryCount,
    flow.memoryTotalCount,
    flow.syncedCount,
    rawRecordsRead,
    flow.memoryRemainingCount,
    memoryStep?.status,
    isFirstContext,
    t,
  ]);

  const labels: Record<InstallStepId, string> = {
    install: t('pluginInstallPanel.stepInstall'),
    enable: t('pluginInstallPanel.stepEnable'),
    sync: t('pluginInstallPanel.stepSync'),
    memory: isFirstContext
      ? flow.syncDeferred
        ? t('pluginInstallPanel.memoryWaitingForSync')
        : memoryHasNoNewRecords
          ? t('pluginInstallPanel.firstContextNoNewTitle')
          : memoryStep?.status === 'done'
            ? t('pluginInstallPanel.firstContextReadyTitle')
            : t('pluginInstallPanel.stepFirstContext')
      : flow.syncDeferred
        ? t('pluginInstallPanel.memoryWaitingForSync')
        : memoryHasNoNewRecords
          ? t('pluginInstallPanel.memoryNoNewTitle')
          : flow.memoryReady
            ? t('pluginInstallPanel.readyTitle')
            : flow.backfillNote
              ? t('pluginInstallPanel.memoryReadying')
              : t('pluginInstallPanel.stepMemory'),
  };

  const details: Partial<Record<InstallStepId, string>> = {
    sync: syncProgressDetail,
    memory: memoryProgressDetail,
  };
  const closeLabel =
    flow.phase === 'done' && flow.backfillNote && !flow.memoryReady
      ? t('pluginInstallPanel.closeBackground')
      : t('pluginInstallPanel.close');
  const closeDisabled = flow.phase === 'loading' || flow.phase === 'running';
  const registryStatusMessage = (
    registryState === 'loading'
      ? t('app:settings.marketplace.loading')
      : registryState === 'not_found'
        ? t('app:settings.marketplace.empty')
        : registryState === 'error'
          ? t('app:settings.marketplace.error')
          : undefined
  );

  if (!open) {
    return null;
  }

  // Install-mode consent gate: show the declared capabilities and require
  // acceptance before the registry install runs. Already-installed plugins
  // (installMode=false) were consented at install time and skip this.
  if (installMode && !consented) {
    return (
      <PluginConsentDialog
        open
        mode="install"
        pluginName={name}
        pluginIcon={icon}
        version={entryMeta?.version ?? ''}
        official={entryMeta?.official}
        capabilities={entryMeta?.capabilities ?? []}
        executionMode={entryMeta?.executionMode}
        confirmDisabled={registryState !== 'ready' || !entryMeta?.installFingerprint}
        statusMessage={registryStatusMessage}
        onConfirm={() => {
          if (registryState === 'ready' && entryMeta?.installFingerprint) {
            setConsented(true);
          }
        }}
        onCancel={closePanel}
      />
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) closePanel();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2.5">
            {icon ? (
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted/55">
                <PluginIcon iconId={icon} className="h-5 w-5" />
              </span>
            ) : null}
            <span>{name}</span>
          </DialogTitle>
          <DialogDescription>
            {isHistoryImport
              ? t('pluginInstallPanel.importerDescription')
              : isFirstContext
              ? t('pluginInstallPanel.firstContextDescription')
              : flow.description ?? t('pluginInstallPanel.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 pb-2">
          {flow.phase === 'unsupported' ? (
            <p className="text-sm text-muted-foreground">{t('pluginInstallPanel.unsupported')}</p>
          ) : flow.phase === 'awaiting_fields' ? (
            <div className="space-y-3">
              <p className="text-xs font-medium text-muted-foreground">
                {t('pluginInstallPanel.fieldsTitle')}
              </p>
              <PluginSettingsFields
                fields={fieldSpecs}
                values={values as Record<string, any>}
                onChange={handleFieldChange}
                pluginId={pluginId ?? undefined}
              />
            </div>
          ) : (
            <InstallStepper steps={flow.steps} labels={labels} details={details} />
          )}

          {flow.phase === 'done' && isHistoryImport ? (
            <p className="mt-3 text-xs text-muted-foreground">
              {t('pluginInstallPanel.importerInstalledDescription')}
            </p>
          ) : flow.phase === 'done' && isFirstContext && !flow.syncDeferred ? (
            <p className="mt-3 text-xs text-muted-foreground">
              {t('pluginInstallPanel.firstContextBackfillHint')}
            </p>
          ) : flow.phase === 'done' && flow.backfillNote ? (
            <p className="mt-3 text-xs text-muted-foreground">
              {flow.syncDeferred
                ? t('pluginInstallPanel.syncBackgroundNote')
                : t('pluginInstallPanel.backfillNote')}
            </p>
          ) : null}
          {flow.phase === 'error' && flow.error ? (
            <p className="mt-3 text-xs text-destructive">{flow.error}</p>
          ) : null}
        </div>

        <DialogFooter>
          {flow.phase === 'awaiting_fields' ? (
            <button
              type="button"
              className="min-w-[5.5rem] rounded-md border border-primary/40 px-3 py-1.5 text-center text-xs font-medium text-primary transition hover:bg-primary/10 disabled:opacity-50"
              disabled={!allRequiredSatisfied}
              onClick={() => flow.submitFields(values)}
            >
              {t('pluginInstallPanel.connect')}
            </button>
          ) : flow.phase === 'error' ? (
            <button
              type="button"
              className="min-w-[5.5rem] rounded-md border border-primary/40 px-3 py-1.5 text-center text-xs font-medium text-primary transition hover:bg-primary/10"
              onClick={flow.retry}
            >
              {t('pluginInstallPanel.errorRetry')}
            </button>
          ) : (
            <button
              type="button"
              className="min-w-[5.5rem] rounded-md border border-border px-3 py-1.5 text-center text-xs font-medium transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
              disabled={closeDisabled}
              onClick={closePanel}
            >
              {closeLabel}
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PluginInstallPanel;
