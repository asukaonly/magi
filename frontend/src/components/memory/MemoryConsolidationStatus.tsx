import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type MemoryConsolidationStatus as ProcessingStatus } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';

export const MemoryConsolidationStatus = ({ onCompleted }: { onCompleted: () => Promise<void> }) => {
  const { t, i18n } = useTranslation('app');
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const lastRun = useRef<number | null | undefined>(undefined);
  const awaitingCompletion = useRef(false);
  const requestVersion = useRef(0);
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;
  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const next = await memoryApi.getConsolidationStatus();
      if (version !== requestVersion.current) return;
      const processing = ['queued', 'running'].includes(next.state);
      const completed = !processing && (awaitingCompletion.current || (lastRun.current !== undefined && next.last_run_at && next.last_run_at !== lastRun.current));
      awaitingCompletion.current = processing;
      setStatus(next);
      setError(false);
      if (completed) {
        await onCompletedRef.current();
      }
      if (!processing) lastRun.current = next.last_run_at ?? null;
    } catch { if (version === requestVersion.current) setError(true); }
  }, []);
  useEffect(() => { void refresh(); return () => { requestVersion.current += 1; }; }, [refresh]);
  useEffect(() => {
    if (!status || !['queued', 'running'].includes(status.state)) return;
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh, status]);
  const request = async () => {
    setBusy(true);
    requestVersion.current += 1;
    try {
      const result = await memoryApi.requestConsolidation();
      if (result.scheduled) {
        awaitingCompletion.current = true;
        setStatus((current) => ({ ...current, state: 'queued', reason_code: 'queued', pending_events: current?.pending_events ?? 0, stats: current?.stats ?? {} }));
      }
      else await refresh();
      setError(false);
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <section aria-live="polite" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4 text-sm">
    <div>
      <p>{error ? t('memory.consolidation.loadFailed') : t(`memory.consolidation.reasons.${status?.reason_code ?? 'loading'}`)}</p>
      {status?.last_run_at ? <p className="mt-1 text-xs text-muted-foreground">{t('memory.consolidation.lastRun', { time: new Date(status.last_run_at * 1000).toLocaleString(i18n.language) })}</p> : null}
      {status?.model_selection === 'unavailable' ? <p className="mt-1 text-xs text-muted-foreground">{t('memory.consolidation.modelUnavailable')}</p> : null}
    </div>
    {error ? <Button variant="outline" size="sm" onClick={() => void refresh()}>{t('memory.pending.retry')}</Button> : status && !['disabled', 'unavailable', 'queued', 'running'].includes(status.state) ? <Button variant="outline" size="sm" disabled={busy} onClick={() => void request()}>{t('memory.consolidation.request')}</Button> : null}
  </section>;
};
