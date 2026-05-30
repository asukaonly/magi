import React, { useCallback, useEffect, useMemo, useState } from 'react';

import type { ActivationFlowSpec, ExtensionFieldSpec } from '@/api/modules/plugins';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/**
 * Resolve a plugin-i18n translated label for a flow text field, with raw
 * fallback. Mirrors the resolution order used inside
 * ``TimelineSourcesSection.tsx`` so the extracted dialog stays behaviour-
 * compatible with the inline implementation it replaces.
 */
const getActivationText = (
  flow: ActivationFlowSpec,
  key: 'title' | 'description' | 'confirm_label' | 'cancel_label',
  fallback: string,
): string => {
  const translatedKey = `${key}_translated` as
    | 'title_translated'
    | 'description_translated'
    | 'confirm_label_translated'
    | 'cancel_label_translated';
  return flow[translatedKey] || fallback;
};

/**
 * Treat the field as "satisfied" when:
 *   - it is not required, OR
 *   - it has a non-empty value (strings trimmed; booleans always pass; arrays
 *     non-empty; everything else just needs to be defined).
 */
const isFieldSatisfied = (field: ExtensionFieldSpec, value: unknown): boolean => {
  if (!field.required) {
    return true;
  }
  if (value === undefined || value === null) {
    return false;
  }
  if (typeof value === 'string') {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return true;
};

export interface PluginActivationDialogProps {
  /** Controls dialog visibility. When ``false`` the component renders nothing. */
  open: boolean;
  /** Called when the dialog is dismissed (cancel button or outside click). */
  onClose: () => void;
  /** The activation flow spec describing fields, labels, and i18n overrides. */
  flow: ActivationFlowSpec;
  /** Initial field values; re-seeded into local state whenever ``open`` flips to true. */
  initialValues: Record<string, unknown>;
  /**
   * Confirmation handler. Receives the current field values and may be async; the
   * dialog shows a busy state until the promise resolves or rejects.
   */
  onConfirm: (values: Record<string, unknown>) => Promise<void>;
  /**
   * Optional plugin id forwarded to ``PluginSettingsFields`` for per-plugin
   * field rendering hooks (resource pickers etc.). Omit when the caller does
   * not have a plugin context yet (e.g. preview surfaces).
   */
  pluginId?: string;
}

/**
 * Seed the form state from each field's `default`, then overlay any caller
 * `initialValues`. Without this the values map starts empty, so a field whose
 * visibility depends on another field's value (e.g. the "recent days" input,
 * shown only when the scope select equals "lookback_days") never appears —
 * even though the select *displays* its default option, the underlying value
 * the dependency check reads is still undefined.
 */
const seedValues = (
  flow: ActivationFlowSpec,
  initialValues: Record<string, unknown>,
): Record<string, unknown> => {
  const seed: Record<string, unknown> = {};
  for (const field of flow.fields) {
    if (field.default !== undefined && field.default !== null) {
      seed[field.key] = field.default;
    }
  }
  return { ...seed, ...initialValues };
};

export const PluginActivationDialog: React.FC<PluginActivationDialogProps> = ({
  open,
  onClose,
  flow,
  initialValues,
  onConfirm,
  pluginId,
}) => {
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    seedValues(flow, initialValues),
  );
  const [submitting, setSubmitting] = useState(false);

  // Re-seed local state every time the dialog (re)opens so a stale draft from
  // a previous activation does not leak across opens.
  useEffect(() => {
    if (open) {
      setValues(seedValues(flow, initialValues));
      setSubmitting(false);
    }
  }, [open, flow, initialValues]);

  const allRequiredSatisfied = useMemo(
    () => flow.fields.every((field) => isFieldSatisfied(field, values[field.key])),
    [flow.fields, values],
  );

  const handleFieldChange = useCallback((key: string, nextValue: unknown) => {
    setValues((prev) => ({ ...prev, [key]: nextValue }));
  }, []);

  const handleConfirm = useCallback(async () => {
    if (!allRequiredSatisfied || submitting) {
      return;
    }
    setSubmitting(true);
    try {
      await onConfirm(values);
    } finally {
      setSubmitting(false);
    }
  }, [allRequiredSatisfied, submitting, onConfirm, values]);

  if (!open) {
    return null;
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{getActivationText(flow, 'title', flow.title)}</DialogTitle>
          <DialogDescription>
            {getActivationText(flow, 'description', flow.description)}
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 pb-6">
          <PluginSettingsFields
            fields={flow.fields}
            values={values as Record<string, any>}
            onChange={handleFieldChange}
            pluginId={pluginId}
            disabled={submitting}
          />
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            disabled={submitting}
          >
            {getActivationText(flow, 'cancel_label', flow.cancel_label)}
          </Button>
          <Button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={!allRequiredSatisfied || submitting}
          >
            {getActivationText(flow, 'confirm_label', flow.confirm_label)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PluginActivationDialog;
