import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { pluginsApi } from '@/api/modules/plugins';
import type { ExtensionFieldSpec, PluginCapability } from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
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

/** "netease-music" → "Netease Music" — readable fallback when a plugin has no
 *  localized name in the `pluginNames` i18n map. Mirrors SystemSuggestionSideCard. */
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
const seedFieldValues = (fields: ExtensionFieldSpec[]): Record<string, unknown> => {
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
 * Opened from three entry points via usePluginInstallPanelStore; drives the
 * usePluginInstallFlow state machine and renders, per phase:
 *   - awaiting_fields → the field form (reused PluginSettingsFields + required gate)
 *   - loading / running / done → the InstallStepper with dynamic labels
 *   - unsupported → an honest "can't one-click connect yet" message (no silent no-op)
 *   - error → the message + a retry action
 */
export function PluginInstallPanel(): JSX.Element | null {
  const { t } = useTranslation('onboarding');
  const open = usePluginInstallPanelStore((s) => s.open);
  const pluginId = usePluginInstallPanelStore((s) => s.pluginId);
  const installMode = usePluginInstallPanelStore((s) => s.installMode);
  const closePanel = usePluginInstallPanelStore((s) => s.closePanel);
  const onDone = usePluginInstallPanelStore((s) => s.onDone);

  const [consented, setConsented] = useState(false);
  const [entryMeta, setEntryMeta] = useState<{
    capabilities: PluginCapability[];
    version: string;
    official: boolean;
  } | null>(null);

  // In install mode, hold the connect flow until the user accepts the plugin's
  // declared capabilities (mirrors the marketplace's consent dialog). The flow
  // stays idle while pluginId is null, so installs never run unseen.
  const flowActive = open && (!installMode || consented);
  const flow = usePluginInstallFlow(flowActive ? pluginId : null, installMode);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const doneFiredRef = useRef(false);

  // Reset the consent gate + fetched metadata whenever the panel closes.
  useEffect(() => {
    if (!open) {
      setConsented(false);
      setEntryMeta(null);
    }
  }, [open]);

  // Fetch the plugin's declared capabilities for the install-mode consent gate.
  useEffect(() => {
    if (!open || !installMode || !pluginId) return;
    let cancelled = false;
    void pluginsApi
      .getRegistry()
      .then((reg) => {
        if (cancelled) return;
        const e = reg.plugins.find((p) => p.plugin_id === pluginId);
        setEntryMeta({
          capabilities: e?.capabilities ?? [],
          version: e?.version ?? '',
          official: e?.official ?? false,
        });
      })
      .catch(() => {
        if (!cancelled) setEntryMeta({ capabilities: [], version: '', official: false });
      });
    return () => {
      cancelled = true;
    };
  }, [open, installMode, pluginId]);

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
      onDone?.();
    }
  }, [open, flow.phase, onDone]);

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

  const name = pluginId
    ? t(`pluginNames.${pluginId}`, { defaultValue: humanizePluginId(pluginId) })
    : '';

  const memoryProgressDetail = useMemo(() => {
    const processed = flow.memoryProcessedCount ?? (flow.memoryReady ? flow.memoryCount : null);
    const total = flow.memoryTotalCount ?? flow.syncedCount ?? flow.memoryCount;
    const remaining =
      flow.memoryRemainingCount ??
      (processed != null && total != null ? Math.max(0, total - processed) : null);

    if (processed != null && total != null) {
      return t('pluginInstallPanel.memoryProgress', {
        processed,
        total,
        remaining: remaining ?? Math.max(0, total - processed),
      });
    }
    if (processed != null) {
      return t('pluginInstallPanel.memoryProcessed', { count: processed });
    }
    if (total != null) {
      return t('pluginInstallPanel.memoryTotal', { count: total });
    }
    return undefined;
  }, [
    flow.memoryProcessedCount,
    flow.memoryReady,
    flow.memoryCount,
    flow.memoryTotalCount,
    flow.syncedCount,
    flow.memoryRemainingCount,
    t,
  ]);

  const labels: Record<InstallStepId, string> = {
    install: t('pluginInstallPanel.stepInstall'),
    enable: t('pluginInstallPanel.stepEnable'),
    sync: t('pluginInstallPanel.stepSync'),
    memory: flow.memoryReady
      ? t('pluginInstallPanel.readyTitle')
      : flow.backfillNote
        ? t('pluginInstallPanel.memoryReadying')
        : t('pluginInstallPanel.stepMemory'),
  };

  const details: Partial<Record<InstallStepId, string>> = {
    sync:
      flow.syncedCount != null
        ? t('pluginInstallPanel.syncedCount', { count: flow.syncedCount })
        : undefined,
    memory: memoryProgressDetail,
  };

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
        version={entryMeta?.version ?? ''}
        official={entryMeta?.official}
        capabilities={entryMeta?.capabilities ?? []}
        onConfirm={() => setConsented(true)}
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
          <DialogTitle>{name}</DialogTitle>
          {flow.description ? (
            <DialogDescription>{flow.description}</DialogDescription>
          ) : null}
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

          {flow.phase === 'done' && flow.memoryReady ? (
            <p className="mt-3 text-sm font-medium text-primary">
              ✓ {t('pluginInstallPanel.readyTitle')}
            </p>
          ) : null}
          {flow.phase === 'done' && flow.backfillNote ? (
            <p className="mt-3 text-xs text-muted-foreground">
              {t('pluginInstallPanel.backfillNote')}
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
              className="min-w-[5.5rem] rounded-md border border-border px-3 py-1.5 text-center text-xs font-medium transition hover:bg-muted"
              onClick={closePanel}
            >
              {t('pluginInstallPanel.close')}
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PluginInstallPanel;
