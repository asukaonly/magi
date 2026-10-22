import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type MemoryPostTurnProcessingBacklog } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { useRequestOwner } from '@/hooks/useRequestOwner';

export const MemoryProcessingStatus = ({ pending, failed, postTurn, onRetried, onRefresh }: {
  pending: number;
  failed: number;
  postTurn?: MemoryPostTurnProcessingBacklog | null;
  onRetried: () => void;
  onRefresh?: () => void;
}) => {
  const { t } = useTranslation('app');
  return <div className="space-y-3">
    <ProcessingQueueStatus pending={pending} failed={failed} prefix="memory.processing" retryFailed={memoryApi.retryFailedL2Extractions} onRetried={onRetried} />
    {postTurn === null ? <section className="rounded-xl border border-border p-4" aria-live="polite">
      <p>{t('memory.processing.postTurn.unavailable')}</p>
      {onRefresh ? <Button variant="outline" className="mt-2" onClick={onRefresh}>{t('common.retry')}</Button> : null}
    </section> : postTurn ? <ProcessingQueueStatus pending={postTurn.pending} running={postTurn.claimed} failed={postTurn.failed} prefix="memory.processing.postTurn" retryFailed={memoryApi.retryFailedPostTurn} onRetried={onRetried} /> : null}
  </div>;
};

const ProcessingQueueStatus = ({ pending, running = 0, failed, prefix, retryFailed, onRetried }: {
  pending: number;
  running?: number;
  failed: number;
  prefix: 'memory.processing' | 'memory.processing.postTurn';
  retryFailed: () => Promise<{ queued_count: number; remaining_count: number }>;
  onRetried: () => void;
}) => {
  const { t } = useTranslation('app');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [queued, setQueued] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);
  const submitting = useRef(false);
  const ownRequest = useRequestOwner();
  const retry = async () => {
    if (submitting.current) return;
    submitting.current = true;
    const current = ownRequest('retry');
    setBusy(true); setError(false); setQueued(null);
    try {
      const result = await retryFailed();
      if (!current()) return;
      setQueued(result.queued_count);
      setRemaining(result.remaining_count);
      onRetried();
    } catch { if (current()) setError(true); }
    finally { submitting.current = false; if (current()) setBusy(false); }
  };
  if (!pending && !running && !failed && queued === null) return null;
  return <section className="rounded-xl border border-border p-4" aria-live="polite">
    {pending > 0 ? <p>{t(`${prefix}.pending`, { count: pending })}</p> : null}
    {running > 0 ? <p>{t(`${prefix}.running`, { count: running })}</p> : null}
    {failed > 0 ? <>
      <p className="font-medium text-destructive">{t(`${prefix}.failed`, { count: failed })}</p>
      <p className="mt-1 text-sm text-muted-foreground">{t(`${prefix}.help`)}</p>
      <Button className="mt-3" variant="outline" disabled={busy} onClick={() => void retry()}>
        {t(`${prefix}.${busy ? 'retrying' : 'retry'}`)}
      </Button>
    </> : null}
    {queued !== null ? <p role="status" className="mt-2 text-sm">{t(`${prefix}.queued`, { count: queued })}{remaining > 0 ? ` ${t(`${prefix}.remaining`, { count: remaining })}` : ''}</p> : null}
    {error ? <p role="alert" className="mt-2 text-sm text-destructive">{t(`${prefix}.retryFailed`)}</p> : null}
  </section>;
};
