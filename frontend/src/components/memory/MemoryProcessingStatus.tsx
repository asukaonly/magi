import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';

export const MemoryProcessingStatus = ({ pending, failed, onRetried }: {
  pending: number; failed: number; onRetried: () => void;
}) => {
  const { t } = useTranslation('app');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [queued, setQueued] = useState<number | null>(null);
  const retry = async () => {
    if (busy) return;
    setBusy(true); setError(false);
    try {
      const result = await memoryApi.retryFailedL2Extractions();
      setQueued(result.queued_count);
      onRetried();
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  if (!pending && !failed && queued === null) return null;
  return <section className="rounded-xl border border-border p-4" aria-live="polite">
    {pending > 0 ? <p>{t('memory.processing.pending', { count: pending })}</p> : null}
    {failed > 0 ? <>
      <p className="font-medium text-destructive">{t('memory.processing.failed', { count: failed })}</p>
      <p className="mt-1 text-sm text-muted-foreground">{t('memory.processing.help')}</p>
      <Button className="mt-3" variant="outline" disabled={busy} onClick={() => void retry()}>
        {t(busy ? 'memory.processing.retrying' : 'memory.processing.retry')}
      </Button>
    </> : null}
    {queued !== null ? <p role="status" className="mt-2 text-sm">{t('memory.processing.queued', { count: queued })}</p> : null}
    {error ? <p role="alert" className="mt-2 text-sm text-destructive">{t('memory.processing.retryFailed')}</p> : null}
  </section>;
};
