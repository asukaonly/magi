import { useCallback, useState } from 'react';
import { sensorsApi, type SensorSourceStatusItem } from '../api/modules/sensors';
import { pluginsApi, type ActivationFlowSpec } from '../api/modules/plugins';

export interface ActivationDialogState {
  pluginId: string;
  sourceName: string;
  flow: ActivationFlowSpec;
}

export interface UsePluginActivationOptions {
  /** Fired after a plugin is successfully activated. */
  onSuccess?: (pluginId: string) => void;
}

export interface UsePluginActivationResult {
  dialogState: ActivationDialogState | null;
  openDialog: (pluginId: string) => Promise<void>;
  closeDialog: () => void;
  confirm: (values: Record<string, unknown>) => Promise<void>;
}

/**
 * Shared plugin-activation flow used by the empty-state grid and the system
 * suggestion side card. Mirrors Settings: fetch sensor status -> find the
 * source whose activation_flow matches the plugin -> open the dialog -> on
 * confirm optionally authorize, then persist enabled/configured via
 * pluginsApi.updateSettings.
 */
export function usePluginActivation(
  options: UsePluginActivationOptions = {},
): UsePluginActivationResult {
  const { onSuccess } = options;
  const [dialogState, setDialogState] = useState<ActivationDialogState | null>(null);

  const openDialog = useCallback(async (pluginId: string) => {
    try {
      const status = await sensorsApi.getStatus();
      const match = status.sources.find(
        (source: SensorSourceStatusItem) =>
          source.plugin_id === pluginId && source.activation_flow,
      );
      if (!match || !match.activation_flow) {
        console.error('no activation flow available for plugin', pluginId);
        return;
      }
      setDialogState({
        pluginId,
        sourceName: match.source_name,
        flow: match.activation_flow,
      });
    } catch (err) {
      console.error('failed to fetch sensor status for activation', err);
    }
  }, []);

  const closeDialog = useCallback(() => setDialogState(null), []);

  const confirm = useCallback(
    async (values: Record<string, unknown>) => {
      if (!dialogState) return;
      const { pluginId, sourceName, flow } = dialogState;
      if (flow.authorize_on_confirm) {
        const authResult = await sensorsApi.requestAuthorization(
          sourceName,
          values as Record<string, any>,
        );
        if (!authResult.authorized) {
          throw new Error(authResult.message || 'authorization_denied');
        }
      }
      await pluginsApi.updateSettings(pluginId, {
        ...values,
        [flow.enabled_key]: true,
        [flow.configured_key]: true,
      });
      setDialogState(null);
      onSuccess?.(pluginId);
    },
    [dialogState, onSuccess],
  );

  return { dialogState, openDialog, closeDialog, confirm };
}
