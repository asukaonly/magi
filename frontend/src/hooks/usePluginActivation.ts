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

export interface OpenDialogOptions {
  /**
   * When true, download the plugin from the registry (and wait for the install
   * job to finish) BEFORE opening the activation dialog. Used for plugins that
   * are not yet installed locally. Defaults to off.
   */
  install?: boolean;
}

export interface UsePluginActivationResult {
  dialogState: ActivationDialogState | null;
  /** Plugin id currently being downloaded from the registry (install-first), or null. */
  installingPluginId: string | null;
  openDialog: (pluginId: string, opts?: OpenDialogOptions) => Promise<void>;
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
  const [installingPluginId, setInstallingPluginId] = useState<string | null>(null);

  const openDialog = useCallback(async (pluginId: string, opts?: OpenDialogOptions) => {
    if (opts?.install) {
      setInstallingPluginId(pluginId);
      try {
        await pluginsApi.installFromRegistryWithProgress(pluginId);
      } catch (err) {
        console.error('failed to install plugin from registry', err);
        return;
      } finally {
        setInstallingPluginId(null);
      }
    }
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

  return { dialogState, installingPluginId, openDialog, closeDialog, confirm };
}
