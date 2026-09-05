import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Loader2, QrCode, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import {
  pluginsApi,
  type PluginSettingsActionRunResponse,
  type PluginSettingsActionSpec,
} from '@/api/modules/plugins';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { openExternalUrl } from '@/runtime/desktop';

interface PluginSettingsActionsProps {
  pluginId: string;
  connectionId: string;
  connectionEnabled?: boolean;
  actions: PluginSettingsActionSpec[];
  values: Record<string, any>;
  disabled?: boolean;
  onSettingsUpdates?: (connectionId: string, updates: Record<string, any>) => void;
  onActionSettled?: () => Promise<void> | void;
}

type ActionState = {
  loading: boolean;
  result?: PluginSettingsActionRunResponse;
  error?: string;
};

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const isActionVisible = (action: PluginSettingsActionSpec, values: Record<string, any>) => {
  if (!action.depends_on_key || !action.depends_on_values?.length) {
    return true;
  }
  return action.depends_on_values.includes(String(values[action.depends_on_key] ?? ''));
};

/**
 * Resolution order (Phase 4):
 *   1. ``action.{key}_translated`` (API, plugin i18n)
 *   2. raw ``action[key]`` (English fallback from the manifest)
 */
const getActionCopy = (
  action: PluginSettingsActionSpec,
  key: 'label' | 'description' | 'button_label'
) => {
  const translatedKey = `${key}_translated` as
    | 'label_translated'
    | 'description_translated'
    | 'button_label_translated';
  return action[translatedKey] || action[key];
};

const getQrImageSource = (data: Record<string, any>): string => {
  const raw =
    data.qr_code_url ??
    data.qrcode_url ??
    data.qr_image_url ??
    data.qr_code_image_url ??
    data.qr_code_data_url ??
    data.qr_code_image ??
    data.qrcode_image ??
    '';
  const value = String(raw || '').trim();
  if (!value) {
    return '';
  }
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:')) {
    return value;
  }
  return `data:image/png;base64,${value}`;
};

const getStatusVariant = (status: PluginSettingsActionRunResponse['status'] | undefined) => {
  if (status === 'succeeded') {
    return 'default';
  }
  if (status === 'failed') {
    return 'destructive';
  }
  return 'secondary';
};

const getActionOpenUrl = (result: PluginSettingsActionRunResponse | undefined): string => {
  const raw =
    result?.data?.open_url ??
    result?.data?.authorization_url ??
    result?.data?.verification_uri ??
    '';
  const value = String(raw || '').trim();
  if (!value.startsWith('https://') && !value.startsWith('http://')) {
    return '';
  }
  return value;
};

export const PluginSettingsActions: React.FC<PluginSettingsActionsProps> = ({
  pluginId,
  connectionId,
  connectionEnabled = false,
  actions,
  values,
  disabled = false,
  onSettingsUpdates,
  onActionSettled,
}) => {
  const { t } = useTranslation('app');
  const mountedRef = useRef(true);
  const currentConnection = useRef(connectionId);
  currentConnection.current = connectionId;
  const runs = useRef<Record<string, number>>({});
  const inFlight = useRef(new Set<string>());
  const openedActionUrlsRef = useRef<Set<string>>(new Set());
  const [actionStates, setActionStates] = useState<Record<string, ActionState>>({});

  useEffect(() => {
    mountedRef.current = true;
    setActionStates({});
    openedActionUrlsRef.current.clear();
    runs.current = {};
    return () => {
      mountedRef.current = false;
    };
  }, [connectionId]);

  const visibleActions = useMemo(
    () => [...actions].filter((action) => isActionVisible(action, values)).sort((a, b) => a.order - b.order),
    [actions, values]
  );

  if (visibleActions.length === 0) {
    return null;
  }

  const completeAction = async (result: PluginSettingsActionRunResponse) => {
    if (result.status === 'succeeded') {
      if (Object.keys(result.settings_updates || {}).length > 0) {
        onSettingsUpdates?.(connectionId, result.settings_updates);
      }
      toast.success(result.message || t('settings.pluginActions.feedback.succeeded'));
      await onActionSettled?.();
      return;
    }
    if (result.status === 'failed') {
      toast.error(result.message || t('settings.pluginActions.feedback.failed'));
      return;
    }
    if (result.status === 'cancelled') {
      toast.info(result.message || t('settings.pluginActions.feedback.cancelled'));
    }
    if (result.status === 'uncertain') {
      toast.warning(t('settings.pluginActions.feedback.uncertain'));
      await onActionSettled?.();
    }
  };

  const openResultUrlIfPresent = async (result: PluginSettingsActionRunResponse) => {
    const url = getActionOpenUrl(result);
    if (!url) {
      return;
    }
    const dedupeKey = `${result.session_id || result.action_id}:${url}`;
    if (openedActionUrlsRef.current.has(dedupeKey)) {
      return;
    }
    openedActionUrlsRef.current.add(dedupeKey);
    try {
      await openExternalUrl(url);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error || 'unknown');
      toast.error(t('settings.pluginActions.feedback.failedWithMessage', { message }));
    }
  };

  const pollAction = async (
    action: PluginSettingsActionSpec,
    initialResult: PluginSettingsActionRunResponse,
    run: number,
  ) => {
    const isCurrent = () => mountedRef.current && currentConnection.current === connectionId && runs.current[action.action_id] === run;
    let current = initialResult;
    const startedAt = Date.now();
    const timeoutMs = Math.max(action.timeout_ms || 0, 1_000);
    const pollIntervalMs = Math.max(action.poll_interval_ms || 2_000, 1_000);

    while (
      isCurrent() &&
      current.status === 'pending' &&
      Date.now() - startedAt < timeoutMs
    ) {
      await delay(pollIntervalMs);
      if (!isCurrent()) {
        return;
      }
      current = await pluginsApi.pollSettingsAction(
        connectionId,
        action.action_id,
        current.session_id,
        values
      );
      if (!isCurrent()) return;
      if (current.connection_id !== connectionId || current.plugin_id !== pluginId) throw new Error('Settings action returned a different connection');
      void openResultUrlIfPresent(current);
      setActionStates((prev) => ({
        ...prev,
        [action.action_id]: { loading: current.status === 'pending', result: current },
      }));
    }

    if (!isCurrent()) {
      return;
    }
    if (current.status === 'pending') {
      setActionStates((prev) => ({
        ...prev,
        [action.action_id]: {
          loading: false,
          result: {
            ...current,
            status: 'uncertain',
            message: t('settings.pluginActions.feedback.uncertain'),
          },
        },
      }));
      toast.warning(t('settings.pluginActions.feedback.uncertain'));
      return;
    }
    await completeAction(current);
  };

  const startAction = async (action: PluginSettingsActionSpec) => {
    const inFlightKey = `${connectionId}:${action.action_id}`;
    if (inFlight.current.has(inFlightKey)) return;
    inFlight.current.add(inFlightKey);
    const run = (runs.current[action.action_id] ?? 0) + 1;
    runs.current[action.action_id] = run;
    const isCurrent = () => mountedRef.current && currentConnection.current === connectionId && runs.current[action.action_id] === run;
    setActionStates((prev) => ({
      ...prev,
      [action.action_id]: { loading: true },
    }));
    try {
      const result = await pluginsApi.startSettingsAction(connectionId, action.action_id, values);
      if (!isCurrent()) {
        return;
      }
      if (result.connection_id !== connectionId || result.plugin_id !== pluginId) throw new Error('Settings action returned a different connection');
      setActionStates((prev) => ({
        ...prev,
        [action.action_id]: { loading: result.status === 'pending', result },
      }));
      void openResultUrlIfPresent(result);
      if (result.status === 'pending') {
        await pollAction(action, result, run);
        return;
      }
      await completeAction(result);
    } catch {
      if (!isCurrent()) return;
      const message = t('settings.pluginActions.feedback.uncertain');
      setActionStates((prev) => ({
        ...prev,
        [action.action_id]: { loading: false, result: {
          connection_id: connectionId, plugin_id: pluginId, action_id: action.action_id,
          session_id: '', status: 'uncertain', message, data: {}, settings_updates: {},
        } },
      }));
      toast.warning(message);
    } finally {
      inFlight.current.delete(inFlightKey);
    }
  };

  const cancelAction = async (action: PluginSettingsActionSpec, sessionId: string) => {
    runs.current[action.action_id] = (runs.current[action.action_id] ?? 0) + 1;
    try {
      const result = await pluginsApi.cancelSettingsAction(connectionId, action.action_id, sessionId);
      if (!mountedRef.current || currentConnection.current !== connectionId) {
        return;
      }
      if (result.connection_id !== connectionId || result.plugin_id !== pluginId) throw new Error('Settings action returned a different connection');
      setActionStates((prev) => ({
        ...prev,
        [action.action_id]: { loading: false, result },
      }));
      await completeAction(result);
    } catch {
      if (!mountedRef.current || currentConnection.current !== connectionId) return;
      const message = t('settings.pluginActions.feedback.uncertain');
      setActionStates((prev) => ({ ...prev, [action.action_id]: { loading: false, result: {
        connection_id: connectionId, plugin_id: pluginId, action_id: action.action_id,
        session_id: sessionId, status: 'uncertain', message, data: {}, settings_updates: {},
      } } }));
      toast.warning(message);
    }
  };

  return (
    <div className="space-y-5">
      {visibleActions.map((action) => {
        const state = actionStates[action.action_id];
        const result = state?.result;
        const qrImageSource = result?.data ? getQrImageSource(result.data) : '';
        const running = Boolean(state?.loading && result?.status !== 'succeeded');
        const canCancel = Boolean(result?.session_id && result.status === 'pending');
        const status = result?.status;

        return (
          <section
            key={action.action_id}
            className="space-y-4 border-b border-[hsl(var(--settings-subnav-border)/0.6)] py-4 last:border-b-0"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  {action.presentation === 'qr_code' ? <QrCode className="h-4 w-4 text-primary" /> : null}
                  {getActionCopy(action, 'label')}
                  {status ? <Badge variant={getStatusVariant(status)}>{status}</Badge> : null}
                </div>
                {action.description ? (
                  <p className="max-w-3xl text-xs leading-6 text-muted-foreground">
                    {getActionCopy(action, 'description')}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {canCancel ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (result?.session_id) {
                        void cancelAction(action, result.session_id);
                      }
                    }}
                  >
                    {t('settings.pluginActions.actions.cancel')}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant={action.destructive ? 'destructive' : 'outline'}
                  size="sm"
                  disabled={disabled || running || status === 'uncertain' || (action.requires_enabled && !connectionEnabled)}
                  onClick={() => void startAction(action)}
                >
                  {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  {getActionCopy(action, 'button_label')}
                </Button>
              </div>
            </div>

            {action.presentation === 'qr_code' && qrImageSource ? (
              <div className="grid gap-4 md:grid-cols-[10rem_minmax(0,1fr)]">
                <div className="flex h-40 w-40 items-center justify-center rounded-md border border-input bg-background p-3">
                  <img
                    src={qrImageSource}
                    alt={getActionCopy(action, 'label')}
                    className="h-full w-full object-contain"
                  />
                </div>
                <div className="space-y-2 text-sm text-muted-foreground">
                  {result?.message ? <p>{result.message}</p> : null}
                  {result?.data?.status ? (
                    <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                      {String(result.data.status)}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            {result?.message && action.presentation !== 'qr_code' ? (
              <div
                className={cn(
                  'flex items-center gap-2 text-xs',
                  result.status === 'failed' ? 'text-destructive' : 'text-muted-foreground'
                )}
              >
                {result.status === 'succeeded' ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
                {result.status === 'failed' ? <XCircle className="h-3.5 w-3.5" /> : null}
                {result.message}
              </div>
            ) : null}
            {state?.error ? <p className="text-xs text-destructive">{state.error}</p> : null}
          </section>
        );
      })}
    </div>
  );
};

export default PluginSettingsActions;
