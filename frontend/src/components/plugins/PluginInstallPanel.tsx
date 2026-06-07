import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { ExtensionFieldSpec } from '@/api/modules/plugins';
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

  const flow = usePluginInstallFlow(open ? pluginId : null, installMode);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const doneFiredRef = useRef(false);

  // Fire the entry point's onDone exactly once when the flow succeeds (`done`).
  // Reset the guard when the panel closes so a later open can fire again.
  useEffect(() => {
    if (!open) {
      doneFiredRef.current = false;
      return;
    }
    if (flow.phase === 'done' && !doneFiredRef.current) {
      doneFiredRef.current = true;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const labels: Record<InstallStepId, string> = {
    install: t('pluginInstallPanel.stepInstall'),
    enable: t('pluginInstallPanel.stepEnable'),
    sync:
      flow.syncedCount != null
        ? t('pluginInstallPanel.syncedCount', { count: flow.syncedCount })
        : t('pluginInstallPanel.stepSync'),
    memory: flow.memoryReady
      ? t('pluginInstallPanel.readyTitle')
      : flow.backfillNote
        ? t('pluginInstallPanel.memoryReadying')
        : t('pluginInstallPanel.stepMemory'),
  };

  if (!open) {
    return null;
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
            <InstallStepper steps={flow.steps} labels={labels} />
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
