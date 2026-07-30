import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  sensorsApi,
  type MemoryReadinessResponse,
  type SensorSourceStatusItem,
} from '../api/modules/sensors';
import {
  isPluginInstallTimeoutError,
  isPluginRegistryChangedError,
  pluginsApi,
  type ActivationFlowSpec,
  type PluginInstallJobSnapshot,
} from '../api/modules/plugins';
import type { PluginInstallPanelContext } from '../stores/pluginInstallPanel';

export type InstallStepId = 'install' | 'enable' | 'sync' | 'memory';
export type StepStatus = 'pending' | 'running' | 'background' | 'done' | 'error' | 'skipped';
export interface InstallStep {
  id: InstallStepId;
  status: StepStatus;
}
export type FlowPhase = 'loading' | 'awaiting_fields' | 'running' | 'done' | 'unsupported' | 'error';

const SYNC_POLL_MS = 1500;
const SYNC_TIMEOUT_MS = 90_000;
const MEMORY_TIMEOUT_MS = 20_000;
const MEMORY_POLL_WAIT_MS = 1_500;
const MEMORY_POLL_PAUSE_MS = 250;
const MEMORY_BACKGROUND_POLL_MS = 3_000;
const FIRST_CONTEXT_MAX_ITEMS_PER_SYNC = 200;

const finiteNumberOrNull = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const readinessInputCount = (readiness: MemoryReadinessResponse | null): number | null => {
  if (!readiness) return null;
  return finiteNumberOrNull(readiness.l1_event_count) ?? finiteNumberOrNull(readiness.l2_total_count);
};

const memoryReadinessComplete = (
  readiness: MemoryReadinessResponse | null,
  panelContext: PluginInstallPanelContext = 'default',
): boolean => {
  if (!readiness) return false;
  const inputCount = readinessInputCount(readiness);
  if (panelContext === 'first_context') {
    return inputCount !== null;
  }
  return !!readiness.l2_ready || inputCount === 0;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const hasOwn = (value: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

function getFieldDefaults(flow: ActivationFlowSpec): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  for (const field of flow.fields ?? []) {
    if (!field.required && hasOwn(field, 'default')) {
      defaults[field.key] = field.default;
    }
  }
  return defaults;
}

function getSensorSettingsPrefix(flow: ActivationFlowSpec): string | null {
  const enabledKey = typeof flow.enabled_key === 'string' ? flow.enabled_key : '';
  if (!enabledKey.startsWith('sensors.') || !enabledKey.endsWith('.enabled')) {
    return null;
  }
  return enabledKey.slice(0, -'.enabled'.length);
}

function getFirstContextHostDefaults(flow: ActivationFlowSpec): Record<string, unknown> {
  const prefix = getSensorSettingsPrefix(flow);
  if (!prefix) {
    return {};
  }
  return {
    [`${prefix}.max_items_per_sync`]:
      flow.first_context?.max_items_per_sync ?? FIRST_CONTEXT_MAX_ITEMS_PER_SYNC,
  };
}

function applyFirstContextDefaults(
  flow: ActivationFlowSpec,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const overrides = getFirstContextOverrides(flow);
  return {
    ...getFieldDefaults(flow),
    ...getFirstContextHostDefaults(flow),
    ...values,
    ...(overrides ?? {}),
  };
}

function getFirstContextOverrides(flow: ActivationFlowSpec): Record<string, unknown> | null {
  if (!isRecord(flow.first_context)) {
    return null;
  }
  const overrides = flow.first_context.settings_overrides;
  if (!isRecord(overrides)) {
    return null;
  }
  return overrides;
}

function visibleFlowForPanelContext(
  flow: ActivationFlowSpec,
  panelContext: PluginInstallPanelContext,
): ActivationFlowSpec {
  if (panelContext !== 'first_context') {
    return flow;
  }
  const overrides = getFirstContextOverrides(flow);
  const defaultValues = getFieldDefaults(flow);
  const hiddenFieldKeys = new Set([
    ...Object.keys(defaultValues),
    ...Object.keys(overrides ?? {}),
  ]);
  return {
    ...flow,
    fields: (flow.fields ?? []).filter((field) => !hiddenFieldKeys.has(field.key)),
  };
}

export interface UsePluginInstallFlowResult {
  phase: FlowPhase;
  steps: InstallStep[];
  flow: ActivationFlowSpec | null;
  sourceName: string | null;
  description: string | null;
  installProgress: PluginInstallJobSnapshot | null;
  syncedCount: number | null;
  syncedRawCount: number | null;
  syncDeferred: boolean;
  memoryReady: boolean;
  memoryCount: number | null;
  memoryTotalCount: number | null;
  memoryProcessedCount: number | null;
  memoryRemainingCount: number | null;
  backfillNote: boolean;
  error: string | null;
  submitFields: (values: Record<string, unknown>) => void;
  retry: () => void;
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * State machine that drives the honest plugin-connect flow for the
 * PluginInstallPanel. Phases:
 *
 *   loading → [awaiting_fields] → running(enable→sync→memory)
 *           → done | unsupported | error
 *
 * Reuses the existing sensors/plugins API surface plus Phase-B's
 * getMemoryReadiness/installProgress.
 *
 * Honest signals:
 *   - ① install: real installFromRegistryWithProgress onProgress (install mode only).
 *   - ② enable: optional authorize, then updateSettings (instant).
 *   - ③ sync: trigger requestSync, then poll /sensors/status until the source's
 *     last_success advances beyond the baseline; "soft-done" on timeout (work
 *     continues in the background, the bell surfaces it) + backfillNote.
 *   - ④ memory: short bounded getMemoryReadiness polls. Normal plugin panels
 *     wait for l2_ready; first-context onboarding only needs L1 samples for
 *     the first chat, so it finishes after the readiness count is available.
 *     Each poll refreshes the visible counts.
 *
 * A plugin with no activation_flow lands on `unsupported` instead of the
 * previous silent no-op.
 */
export function usePluginInstallFlow(
  pluginId: string | null,
  installMode: boolean,
  panelContext: PluginInstallPanelContext = 'default',
  expectedRegistryFingerprint: string | null = null,
  onRegistryChanged?: () => void,
): UsePluginInstallFlowResult {
  const { t } = useTranslation('app');
  const [phase, setPhase] = useState<FlowPhase>('loading');
  const [flow, setFlow] = useState<ActivationFlowSpec | null>(null);
  const [sourceName, setSourceName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [installProgress, setInstallProgress] = useState<PluginInstallJobSnapshot | null>(null);
  const [syncedCount, setSyncedCount] = useState<number | null>(null);
  const [syncedRawCount, setSyncedRawCount] = useState<number | null>(null);
  const [syncDeferred, setSyncDeferred] = useState(false);
  const [memoryReady, setMemoryReady] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [memoryTotalCount, setMemoryTotalCount] = useState<number | null>(null);
  const [memoryProcessedCount, setMemoryProcessedCount] = useState<number | null>(null);
  const [memoryRemainingCount, setMemoryRemainingCount] = useState<number | null>(null);
  const [backfillNote, setBackfillNote] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<InstallStep[]>([]);
  const flowKey = pluginId
    ? `${pluginId}:${installMode ? 'install' : 'connect'}:${panelContext}:${expectedRegistryFingerprint ?? ''}`
    : null;
  const [stateKey, setStateKey] = useState<string | null>(null);
  const startedRef = useRef(false);
  const runTokenRef = useRef(0);
  const fieldsResolveRef = useRef<((v: Record<string, unknown>) => void) | null>(null);

  const resetTransientState = useCallback(() => {
    setPhase('loading');
    setFlow(null);
    setSourceName(null);
    setDescription(null);
    setInstallProgress(null);
    setSyncedCount(null);
    setSyncedRawCount(null);
    setSyncDeferred(false);
    setMemoryReady(false);
    setMemoryCount(null);
    setMemoryTotalCount(null);
    setMemoryProcessedCount(null);
    setMemoryRemainingCount(null);
    setBackfillNote(false);
    setError(null);
    setSteps([]);
  }, []);

  const setStep = useCallback((id: InstallStepId, status: StepStatus) => {
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, status } : s)));
  }, []);

  const findSource = useCallback(
    async (pid: string): Promise<SensorSourceStatusItem | undefined> => {
      const status = await sensorsApi.getStatus();
      return status.sources.find((s) => s.plugin_id === pid);
    },
    [],
  );

  const applyMemoryReadiness = useCallback((readiness: MemoryReadinessResponse) => {
    const l1Count = finiteNumberOrNull(readiness.l1_event_count);
    const total = finiteNumberOrNull(readiness.l2_total_count) ?? l1Count;
    const remaining = finiteNumberOrNull(readiness.l2_remaining_count);
    const processed =
      finiteNumberOrNull(readiness.l2_processed_count) ??
      (total != null && remaining != null
        ? Math.max(0, total - remaining)
        : readiness.l2_ready
          ? total
          : l1Count);

    setMemoryReady(!!readiness.l2_ready);
    setMemoryCount(l1Count);
    setMemoryTotalCount(total);
    setMemoryProcessedCount(processed);
    setMemoryRemainingCount(remaining);
  }, []);

  useEffect(() => {
    runTokenRef.current += 1;
    fieldsResolveRef.current = null;
    startedRef.current = false;
    setStateKey(flowKey);
    resetTransientState();
  }, [flowKey, resetTransientState]);

  const run = useCallback(async (runToken: number) => {
    if (!pluginId || (installMode && !expectedRegistryFingerprint)) return;
    const isActive = () => runTokenRef.current === runToken;
    setError(null);
    setFlow(null);
    setSourceName(null);
    setDescription(null);
    const initialSteps: InstallStep[] = [
      ...(installMode ? [{ id: 'install' as const, status: 'pending' as const }] : []),
      { id: 'enable', status: 'pending' },
      { id: 'sync', status: 'pending' },
      { id: 'memory', status: 'pending' },
    ];
    setSteps(initialSteps);
    setPhase('loading');
    setInstallProgress(null);
    setSyncedCount(null);
    setSyncedRawCount(null);
    setSyncDeferred(false);
    setMemoryReady(false);
    setMemoryCount(null);
    setMemoryTotalCount(null);
    setMemoryProcessedCount(null);
    setMemoryRemainingCount(null);
    setBackfillNote(false);

    try {
      // ① install (registry only)
      if (installMode) {
        const confirmedFingerprint = expectedRegistryFingerprint;
        if (!confirmedFingerprint) return;
        setStep('install', 'running');
        await pluginsApi.installFromRegistryWithProgress(
          pluginId,
          confirmedFingerprint,
          (snap) => {
            if (isActive()) setInstallProgress(snap);
          },
        );
        if (!isActive()) return;
        setStep('install', 'done');
      }

      // fetch the activation flow
      const src = await findSource(pluginId);
      if (!isActive()) return;
      if (!src || !src.activation_flow) {
        setPhase('unsupported');
        return;
      }
      const visibleFlow = visibleFlowForPanelContext(src.activation_flow, panelContext);
      setFlow(visibleFlow);
      setSourceName(src.source_name);
      setDescription(src.description_translated || src.description || null);

      // fields gate
      let values: Record<string, unknown> = {};
      if ((visibleFlow.fields?.length ?? 0) > 0) {
        setPhase('awaiting_fields');
        values = await new Promise<Record<string, unknown>>((resolve) => {
          fieldsResolveRef.current = resolve;
        });
        if (!isActive()) return;
      }
      if (panelContext === 'first_context') {
        values = applyFirstContextDefaults(src.activation_flow, values);
      }
      setPhase('running');

      // ② enable (authorize + config write)
      setStep('enable', 'running');
      if (src.activation_flow.authorize_on_confirm) {
        const auth = await sensorsApi.requestAuthorization(
          src.source_name,
          values as Record<string, any>,
        );
        if (!isActive()) return;
        if (!auth.authorized) throw new Error(auth.message || 'authorization_denied');
      }
      await pluginsApi.updateSettings(pluginId, {
        ...values,
        [src.activation_flow.enabled_key]: true,
        [src.activation_flow.configured_key]: true,
      });
      if (!isActive()) return;
      setStep('enable', 'done');

      // ③ sync (trigger + poll status until last_success advances, or timeout)
      setStep('sync', 'running');
      const baseSuccess = src.last_success ?? null;
      await sensorsApi.requestSync(
        src.source_name,
        panelContext === 'first_context' ? { firstContext: true } : undefined,
      );
      if (!isActive()) return;
      const deadline = Date.now() + SYNC_TIMEOUT_MS;
      let synced = false;
      while (Date.now() < deadline) {
        await sleep(SYNC_POLL_MS);
        if (!isActive()) return;
        const cur = await findSource(pluginId);
        if (!isActive()) return;
        if (cur && cur.last_success && cur.last_success !== baseSuccess) {
          setSyncedCount(typeof cur.last_result_count === 'number' ? cur.last_result_count : null);
          setSyncedRawCount(
            typeof cur.last_raw_result_count === 'number' ? cur.last_raw_result_count : null,
          );
          synced = true;
          break;
        }
      }
      // soft-done on timeout: background sync continues and the bell notifies.
      setStep('sync', 'done');
      if (!synced) {
        setSyncDeferred(true);
        setBackfillNote(true);
        setStep('memory', 'skipped');
        setPhase('done');
        return;
      }

      // ④ build memory (short polling — backend flushes + reports the source backlog)
      setStep('memory', 'running');
      const memoryDeadline = Date.now() + MEMORY_TIMEOUT_MS;
      const isFirstContext = panelContext === 'first_context';
      let latestReadiness: MemoryReadinessResponse | null = null;
      let pollingMemory = true;
      while (pollingMemory) {
        const remainingWait = Math.max(0, memoryDeadline - Date.now());
        const readiness = await sensorsApi.getMemoryReadiness(src.source_name, {
          maxWaitMs: isFirstContext ? 0 : Math.min(MEMORY_POLL_WAIT_MS, remainingWait),
        });
        if (!isActive()) return;
        latestReadiness = readiness;
        applyMemoryReadiness(readiness);
        const inputCount = readinessInputCount(readiness);
        if (
          memoryReadinessComplete(readiness, panelContext) ||
          inputCount === 0 ||
          Date.now() >= memoryDeadline
        ) {
          pollingMemory = false;
        } else {
          await sleep(MEMORY_POLL_PAUSE_MS);
          if (!isActive()) return;
        }
      }
      const latestInputCount = readinessInputCount(latestReadiness);
      const memoryIsReady = memoryReadinessComplete(latestReadiness, panelContext);
      if (!isFirstContext && !latestReadiness?.l2_ready && latestInputCount !== 0) {
        setBackfillNote(true);
      }
      // When the bounded wait expires, the source is connected but memory is
      // still being organized by the background worker. Keep the visual step
      // honest instead of rendering a fake 100% completion.
      setStep('memory', memoryIsReady ? 'done' : 'background');
      setPhase('done');
      while (!memoryIsReady && isActive()) {
        await sleep(MEMORY_BACKGROUND_POLL_MS);
        if (!isActive()) return;
        try {
          const readiness = await sensorsApi.getMemoryReadiness(src.source_name, {
            maxWaitMs: MEMORY_POLL_WAIT_MS,
          });
          if (!isActive()) return;
          applyMemoryReadiness(readiness);
          if (memoryReadinessComplete(readiness)) {
            setBackfillNote(false);
            setStep('memory', 'done');
            return;
          }
        } catch {
          // Keep the completed connect flow usable; the background worker and
          // notification surfaces can still report final readiness.
          return;
        }
      }
    } catch (e: any) {
      if (!isActive()) return;
      if (isPluginRegistryChangedError(e)) {
        resetTransientState();
        onRegistryChanged?.();
        return;
      }
      setError(
        isPluginInstallTimeoutError(e)
          ? t('settings.marketplace.feedback.installTimedOut')
          : e?.message || String(e),
      );
      setSteps((prev) => prev.map((s) => (s.status === 'running' ? { ...s, status: 'error' } : s)));
      setPhase('error');
    }
  }, [
    pluginId,
    installMode,
    panelContext,
    expectedRegistryFingerprint,
    onRegistryChanged,
    t,
    resetTransientState,
    setStep,
    findSource,
    applyMemoryReadiness,
  ]);

  useEffect(() => {
    if (
      !pluginId
      || (installMode && !expectedRegistryFingerprint)
      || !flowKey
      || stateKey !== flowKey
      || startedRef.current
    ) return;
    startedRef.current = true;
    void run(runTokenRef.current);
  }, [
    pluginId,
    installMode,
    expectedRegistryFingerprint,
    flowKey,
    stateKey,
    run,
  ]);

  const submitFields = useCallback((values: Record<string, unknown>) => {
    fieldsResolveRef.current?.(values);
    fieldsResolveRef.current = null;
  }, []);

  const retry = useCallback(() => {
    setInstallProgress(null);
    setSyncedCount(null);
    setSyncedRawCount(null);
    setSyncDeferred(false);
    setMemoryReady(false);
    setMemoryCount(null);
    setMemoryTotalCount(null);
    setMemoryProcessedCount(null);
    setMemoryRemainingCount(null);
    setBackfillNote(false);
    startedRef.current = true;
    runTokenRef.current += 1;
    void run(runTokenRef.current);
  }, [run]);

  const stateMatchesRequest = stateKey === flowKey;

  return {
    phase: stateMatchesRequest ? phase : 'loading',
    steps: stateMatchesRequest ? steps : [],
    flow: stateMatchesRequest ? flow : null,
    sourceName: stateMatchesRequest ? sourceName : null,
    description: stateMatchesRequest ? description : null,
    installProgress: stateMatchesRequest ? installProgress : null,
    syncedCount: stateMatchesRequest ? syncedCount : null,
    syncedRawCount: stateMatchesRequest ? syncedRawCount : null,
    syncDeferred: stateMatchesRequest ? syncDeferred : false,
    memoryReady: stateMatchesRequest ? memoryReady : false,
    memoryCount: stateMatchesRequest ? memoryCount : null,
    memoryTotalCount: stateMatchesRequest ? memoryTotalCount : null,
    memoryProcessedCount: stateMatchesRequest ? memoryProcessedCount : null,
    memoryRemainingCount: stateMatchesRequest ? memoryRemainingCount : null,
    backfillNote: stateMatchesRequest ? backfillNote : false,
    error: stateMatchesRequest ? error : null,
    submitFields,
    retry,
  };
}
