import { useCallback, useEffect, useRef, useState } from 'react';
import { sensorsApi, type SensorSourceStatusItem } from '../api/modules/sensors';
import {
  pluginsApi,
  type ActivationFlowSpec,
  type PluginInstallJobSnapshot,
} from '../api/modules/plugins';

export type InstallStepId = 'install' | 'enable' | 'sync' | 'memory';
export type StepStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped';
export interface InstallStep {
  id: InstallStepId;
  status: StepStatus;
}
export type FlowPhase = 'loading' | 'awaiting_fields' | 'running' | 'done' | 'unsupported' | 'error';

const SYNC_POLL_MS = 1500;
const SYNC_TIMEOUT_MS = 90_000;
const MEMORY_WAIT_MS = 20_000;

export interface UsePluginInstallFlowResult {
  phase: FlowPhase;
  steps: InstallStep[];
  flow: ActivationFlowSpec | null;
  sourceName: string | null;
  description: string | null;
  installProgress: PluginInstallJobSnapshot | null;
  syncedCount: number | null;
  memoryReady: boolean;
  memoryCount: number | null;
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
 * Reuses the existing sensors/plugins API surface (the same calls
 * usePluginActivation makes) plus Phase-B's getMemoryReadiness/installProgress.
 *
 * Honest signals:
 *   - ① install: real installFromRegistryWithProgress onProgress (install mode only).
 *   - ② enable: optional authorize, then updateSettings (instant).
 *   - ③ sync: trigger requestSync, then poll /sensors/status until the source's
 *     last_success advances beyond the baseline; "soft-done" on timeout (work
 *     continues in the background, the bell surfaces it) + backfillNote.
 *   - ④ memory: a single bounded getMemoryReadiness call; l2_ready drives a real
 *     ✓, otherwise the step is soft-done ("整理中") + backfillNote — never a fake ✓
 *     and never an error.
 *
 * A plugin with no activation_flow lands on `unsupported` instead of the
 * previous silent no-op.
 */
export function usePluginInstallFlow(
  pluginId: string | null,
  installMode: boolean,
): UsePluginInstallFlowResult {
  const [phase, setPhase] = useState<FlowPhase>('loading');
  const [flow, setFlow] = useState<ActivationFlowSpec | null>(null);
  const [sourceName, setSourceName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [installProgress, setInstallProgress] = useState<PluginInstallJobSnapshot | null>(null);
  const [syncedCount, setSyncedCount] = useState<number | null>(null);
  const [memoryReady, setMemoryReady] = useState(false);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [backfillNote, setBackfillNote] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [steps, setSteps] = useState<InstallStep[]>([]);
  const startedRef = useRef(false);
  const fieldsResolveRef = useRef<((v: Record<string, unknown>) => void) | null>(null);

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

  const run = useCallback(async () => {
    if (!pluginId) return;
    setError(null);
    const initialSteps: InstallStep[] = [
      ...(installMode ? [{ id: 'install' as const, status: 'pending' as const }] : []),
      { id: 'enable', status: 'pending' },
      { id: 'sync', status: 'pending' },
      { id: 'memory', status: 'pending' },
    ];
    setSteps(initialSteps);
    setPhase('loading');

    try {
      // ① install (registry only)
      if (installMode) {
        setStep('install', 'running');
        await pluginsApi.installFromRegistryWithProgress(pluginId, (snap) =>
          setInstallProgress(snap),
        );
        setStep('install', 'done');
      }

      // fetch the activation flow
      const src = await findSource(pluginId);
      if (!src || !src.activation_flow) {
        setPhase('unsupported');
        return;
      }
      setFlow(src.activation_flow);
      setSourceName(src.source_name);
      setDescription(src.description_translated || src.description || null);

      // fields gate
      let values: Record<string, unknown> = {};
      if ((src.activation_flow.fields?.length ?? 0) > 0) {
        setPhase('awaiting_fields');
        values = await new Promise<Record<string, unknown>>((resolve) => {
          fieldsResolveRef.current = resolve;
        });
      }
      setPhase('running');

      // ② enable (authorize + config write)
      setStep('enable', 'running');
      if (src.activation_flow.authorize_on_confirm) {
        const auth = await sensorsApi.requestAuthorization(
          src.source_name,
          values as Record<string, any>,
        );
        if (!auth.authorized) throw new Error(auth.message || 'authorization_denied');
      }
      await pluginsApi.updateSettings(pluginId, {
        ...values,
        [src.activation_flow.enabled_key]: true,
        [src.activation_flow.configured_key]: true,
      });
      setStep('enable', 'done');

      // ③ sync (trigger + poll status until last_success advances, or timeout)
      setStep('sync', 'running');
      const baseSuccess = src.last_success ?? null;
      await sensorsApi.requestSync(src.source_name);
      const deadline = Date.now() + SYNC_TIMEOUT_MS;
      let synced = false;
      while (Date.now() < deadline) {
        await sleep(SYNC_POLL_MS);
        const cur = await findSource(pluginId);
        if (cur && cur.last_success && cur.last_success !== baseSuccess) {
          setSyncedCount(typeof cur.last_result_count === 'number' ? cur.last_result_count : null);
          synced = true;
          break;
        }
      }
      // soft-done on timeout: background sync continues and the bell notifies.
      setStep('sync', 'done');
      if (!synced) setBackfillNote(true);

      // ④ build memory (single bounded call — backend flushes + drains backlog internally)
      setStep('memory', 'running');
      const readiness = await sensorsApi.getMemoryReadiness(src.source_name, {
        maxWaitMs: MEMORY_WAIT_MS,
      });
      setMemoryReady(!!readiness.l2_ready);
      setMemoryCount(typeof readiness.l1_event_count === 'number' ? readiness.l1_event_count : null);
      if (!readiness.l2_ready) setBackfillNote(true);
      // labelled ✓ when memoryReady, "整理中" otherwise — soft-done, never an error.
      setStep('memory', 'done');
      setPhase('done');
    } catch (e: any) {
      setError(e?.message || String(e));
      setSteps((prev) => prev.map((s) => (s.status === 'running' ? { ...s, status: 'error' } : s)));
      setPhase('error');
    }
  }, [pluginId, installMode, setStep, findSource]);

  useEffect(() => {
    if (!pluginId || startedRef.current) return;
    startedRef.current = true;
    void run();
  }, [pluginId, run]);

  const submitFields = useCallback((values: Record<string, unknown>) => {
    fieldsResolveRef.current?.(values);
    fieldsResolveRef.current = null;
  }, []);

  const retry = useCallback(() => {
    setInstallProgress(null);
    setSyncedCount(null);
    setMemoryReady(false);
    setBackfillNote(false);
    startedRef.current = true;
    void run();
  }, [run]);

  return {
    phase,
    steps,
    flow,
    sourceName,
    description,
    installProgress,
    syncedCount,
    memoryReady,
    memoryCount,
    backfillNote,
    error,
    submitFields,
    retry,
  };
}
