import { useId, useRef, useState } from 'react';
import { AlertCircle, Check, ChevronDown, ChevronUp, Loader2, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type MemoryPostTurnProcessingBacklog } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { ConversationFailureDetails, MemoryFailureDetails } from './MemoryFailureDetails';

export const MemoryProcessingStatus = ({ pending, failed, postTurn, onRetried, onRefresh }: {
  pending: number;
  failed: number;
  postTurn?: MemoryPostTurnProcessingBacklog | null;
  onRetried: () => void;
  onRefresh?: () => void;
}) => {
  const { t } = useTranslation('app');
  if (!pending && !failed && postTurn !== null && !postTurn?.pending && !postTurn?.claimed && !postTurn?.failed) return null;
  return <div className="space-y-2" data-testid="memory-processing-status">
    <ProcessingQueueStatus pending={pending} failed={failed} prefix="memory.processing" retryFailed={memoryApi.retryFailedL2Extractions} onRetried={onRetried} />
    {postTurn === null ? <section className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm text-muted-foreground" aria-live="polite">
      <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1">{t('memory.processing.postTurn.unavailable')}</p>
      {onRefresh ? <Button variant="ghost" size="sm" onClick={onRefresh}>{t('common.retry')}</Button> : null}
    </section> : postTurn ? <ProcessingQueueStatus pending={postTurn.pending} running={postTurn.claimed} failed={postTurn.failed} errorKinds={postTurn.error_kinds} prefix="memory.processing.postTurn" retryFailed={memoryApi.retryFailedPostTurn} onRetried={onRetried} /> : null}
  </div>;
};

const ProcessingQueueStatus = ({ pending, running = 0, failed, errorKinds = [], prefix, retryFailed, onRetried }: {
  pending: number;
  running?: number;
  failed: number;
  errorKinds?: string[];
  prefix: 'memory.processing' | 'memory.processing.postTurn';
  retryFailed: () => Promise<{ queued_count: number; remaining_count: number }>;
  onRetried: () => void;
}) => {
  const { t } = useTranslation('app');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [queued, setQueued] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [revision, setRevision] = useState(0);
  const detailsId = useId();
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
      setRevision((value) => value + 1);
      onRetried();
    } catch { if (current()) setError(true); }
    finally { submitting.current = false; if (current()) setBusy(false); }
  };
  if (!pending && !running && !failed && queued === null) return null;
  return <section className={failed > 0 || expanded ? 'rounded-xl bg-muted/40' : ''}>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
      {failed > 0 ? <AlertCircle className="h-4 w-4 shrink-0 text-[hsl(var(--memory-body))]" aria-hidden="true" />
        : pending || running ? <Loader2 className="h-4 w-4 shrink-0 text-muted-foreground motion-safe:animate-spin" aria-hidden="true" />
          : <Check className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
      <div className="min-w-0 flex-1 text-sm" aria-live="polite">
        {failed > 0 ? <p className="font-medium">{t(`${prefix}.failed`, { count: failed })}</p> : null}
        <div className="flex flex-wrap gap-x-3 text-xs leading-5 text-muted-foreground">
          {pending > 0 ? <span>{t(`${prefix}.pending`, { count: pending })}</span> : null}
          {running > 0 ? <span>{t(`${prefix}.running`, { count: running })}</span> : null}
          {!failed && !pending && !running && queued !== null ? <span>{t(`${prefix}.queued`, { count: queued })}</span> : null}
        </div>
      </div>
      {failed > 0 || expanded ? <Button variant="ghost" size="sm" aria-expanded={expanded} aria-controls={detailsId} onClick={() => setExpanded((value) => !value)}>
        {t(`memory.processing.details.${expanded ? 'hide' : 'show'}`)}
        {expanded ? <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />}
      </Button> : null}
    </div>
    {expanded ? <div id={detailsId} className="mx-3 border-t border-border/60 pb-4 pt-4 sm:mx-10">
      <p className="mb-4 text-sm leading-6 text-muted-foreground">{t(`${prefix}.help`)}</p>
      {failed > 0 ? prefix === 'memory.processing'
        ? <MemoryFailureDetails revision={revision} failed={failed} />
        : <ConversationFailureDetails errorKinds={errorKinds} /> : null}
      {failed > 0 ? <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void retry()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden="true" /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />}
          {t(`${prefix}.${busy ? 'retrying' : 'retry'}`)}
        </Button>
        <span className="text-xs text-muted-foreground">{t(`${prefix}.batchHelp`)}</span>
      </div> : null}
      {queued !== null ? <p role="status" className="mt-3 text-sm text-muted-foreground">{t(`${prefix}.queued`, { count: queued })}{remaining > 0 ? ` ${t(`${prefix}.remaining`, { count: remaining })}` : ''}</p> : null}
      {error ? <p role="alert" className="mt-3 text-sm text-destructive">{t(`${prefix}.retryFailed`)}</p> : null}
    </div> : null}
  </section>;
};
