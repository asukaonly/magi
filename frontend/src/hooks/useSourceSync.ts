import { useCallback, useEffect, useRef, useState } from 'react';
import { sourcesApi, type SourceStatusItem, type SourceStatusResponse, type SourceSyncActivity, type SourceSyncMode, type SourceSyncRequestOptions } from '@/api/modules/sources';

export const isSourceSyncActive = (activity: SourceSyncActivity | null | undefined): boolean =>
  Boolean(activity && ['queued', 'running', 'retrying', 'continuing'].includes(activity.status));

interface Tracking {
  mode: SourceSyncMode;
  baseline: string | null;
  jobId: string | null;
  started: number;
}
interface Callbacks {
  onStatus?: (status: SourceStatusResponse) => void;
  onComplete?: (source: SourceStatusItem) => void | Promise<void>;
}

/** Own request admission, job identity, polling and stale-connection retirement. */
export function useSourceSync(input: SourceStatusItem | null | undefined, callbacks: Callbacks = {}) {
  const identity = input ? JSON.stringify([input.connection_id, input.source_name]) : null;
  const [observation, setObservation] = useState<{ input: typeof input; source: SourceStatusItem } | null>(null);
  const source = observation && observation.input === input ? observation.source : input;
  const [submitting, setSubmitting] = useState<SourceSyncMode | null>(null);
  const [tracking, setTracking] = useState<Tracking | null>(null);
  const trackingRef = useRef<Tracking | null>(null);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const latest = useRef({ input, source, callbacks });
  latest.current = { input, source, callbacks };
  const track = useCallback((value: Tracking | null) => {
    trackingRef.current = value;
    setTracking(value);
  }, []);

  useEffect(() => {
    generation.current += 1;
    inFlight.current = false;
    setSubmitting(null);
    track(null);
    return () => { generation.current += 1; };
  }, [identity, track]);

  const activity = source?.sync_activity;
  useEffect(() => {
    if (isSourceSyncActive(activity) && activity) {
      const current = trackingRef.current;
      if (!current || (current.mode === activity.mode && current.baseline !== activity.job_id)) {
        track({ mode: activity.mode, baseline: current?.baseline ?? null, jobId: activity.job_id, started: current?.started ?? Date.now() });
      }
    }
  }, [activity, track]);

  const polling = Boolean(tracking) || isSourceSyncActive(activity);
  useEffect(() => {
    if (!identity || !polling) return;
    const epoch = generation.current;
    let cancelled = false;
    let reading = false;
    const poll = async () => {
      if (reading) return;
      reading = true;
      try {
        const response = await sourcesApi.getStatus();
        if (cancelled || generation.current !== epoch) return;
        const current = latest.current;
        const next = response.sources.find(item => item.connection_id === current.source?.connection_id && item.source_name === current.source.source_name);
        if (!next) return;
        setObservation({ input: current.input, source: next });
        current.callbacks.onStatus?.(response);
        const pending = trackingRef.current;
        const job = next.sync_activity;
        if (!pending) return;
        if (job?.mode === pending.mode && job.job_id !== pending.baseline) {
          if (isSourceSyncActive(job)) {
            track({ ...pending, jobId: job.job_id });
          } else if (['success', 'failed'].includes(job.status) && (!pending.jobId || pending.jobId === job.job_id)) {
            track(null);
            await current.callbacks.onComplete?.(next);
          }
        } else if (!pending.jobId && Date.now() - pending.started > 90_000) {
          // Admission without an observed job expires without claiming completion.
          track(null);
        }
      } catch {
        // A transient read failure does not complete or discard a known job.
      } finally { reading = false; }
    };
    const timer = window.setInterval(() => { void poll(); }, 1000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [identity, polling, track]);

  const request = useCallback(async (options?: SourceSyncRequestOptions): Promise<boolean> => {
    const selected = latest.current.source;
    if (!selected || inFlight.current || trackingRef.current || isSourceSyncActive(selected.sync_activity)) return false;
    const epoch = generation.current;
    const mode = options?.mode ?? 'latest';
    inFlight.current = true;
    setSubmitting(mode);
    try {
      if (options) await sourcesApi.requestSync(selected.source_name, selected.connection_id, options);
      else await sourcesApi.requestSync(selected.source_name, selected.connection_id);
      if (epoch !== generation.current) return false;
      track({ mode, baseline: selected.sync_activity?.job_id ?? null, jobId: null, started: Date.now() });
      return true;
    } catch (error) {
      if (epoch !== generation.current) return false;
      throw error;
    } finally {
      if (epoch === generation.current) { inFlight.current = false; setSubmitting(null); }
    }
  }, [track]);

  return { source, request, submitting, pending: tracking?.mode ?? null,
    busy: submitting ?? tracking?.mode ?? (isSourceSyncActive(activity) ? activity?.mode ?? null : null) };
}
