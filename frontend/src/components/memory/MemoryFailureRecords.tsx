import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import { memoryApi, type MemoryFailureRecord, type MemoryFailureRecords as FailurePage, type MemoryFailureReason } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { APP_EVENTS } from '@/constants/events';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { formatMemoryTimeRange } from '@/utils/memory-time';
import { FailureTechnicalDetail } from './MemoryFailureDetails';

export interface MemoryFailureFilter { source?: string; reason?: MemoryFailureReason }
const PAGE_SIZE = 20;
const isContentRejection = (reason: MemoryFailureReason) => ['content_filter', 'content_inspection_failed'].includes(reason);

export function MemoryFailureRecords({ initialFilter, onClose, onChanged }: {
  initialFilter: MemoryFailureFilter;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t, i18n } = useTranslation('app');
  const [status, setStatus] = useState<'failed' | 'ignored'>('failed');
  const [filter, setFilter] = useState(initialFilter);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<FailurePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [feedback, setFeedback] = useState<{ key: string; count: number } | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const submitting = useRef(false);
  const ownRequest = useRequestOwner(JSON.stringify([status, filter, offset]));
  const ownAction = useRequestOwner();

  const load = useCallback(async (silent = false) => {
    const current = ownRequest('records');
    setLoadError(false);
    if (!silent) { setLoading(true); setPage(null); setOpenId(null); }
    try {
      const result = await memoryApi.getL2FailureRecords({ status, ...filter, limit: PAGE_SIZE, offset });
      if (!current()) return;
      if (offset > 0 && offset >= result.total) {
        setOffset(Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1) * PAGE_SIZE);
      } else setPage(result);
    } catch { if (current()) setLoadError(true); }
    finally { if (current()) setLoading(false); }
  }, [ownRequest, status, filter, offset]);
  useEffect(() => { void load(); return () => { ownRequest('records'); }; }, [load, ownRequest]);
  useCenterRefresh(() => load(true), ['memory']);
  useEffect(() => {
    const clear = () => onClose();
    const invalidate = (event: Event) => {
      const detail: unknown = event instanceof CustomEvent ? event.detail : null;
      if (detail && typeof detail === 'object' && 'resource' in detail && detail.resource !== 'memory') return;
      ownRequest('records'); setPage(null); setOpenId(null); setLoading(true);
    };
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, clear);
    window.addEventListener(APP_EVENTS.CENTER_MAINTENANCE, clear);
    window.addEventListener(APP_EVENTS.CENTER_STATE_CHANGED, invalidate);
    return () => {
      window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, clear);
      window.removeEventListener(APP_EVENTS.CENTER_MAINTENANCE, clear);
      window.removeEventListener(APP_EVENTS.CENTER_STATE_CHANGED, invalidate);
    };
  }, [onClose, ownRequest]);

  const act = async (action: 'ignore' | 'restore' | 'retry', records: MemoryFailureRecord[]) => {
    if (submitting.current || records.length === 0) return;
    submitting.current = true;
    const current = ownAction('action');
    setBusy(true); setActionError(false); setFeedback(null);
    try {
      if (action === 'retry') {
        const result = await memoryApi.retryFailedL2Extractions({ event_ids: records.map((record) => record.event_id) });
        if (!current()) return;
        setFeedback({ key: 'memory.processing.queued', count: result.queued_count });
      } else {
        const result = await memoryApi.setL2FailureDisposition(action, records);
        if (!current()) return;
        setFeedback({ key: result.unchanged_count > 0 ? 'memory.processing.records.changedMeanwhile' : `memory.processing.records.${action === 'ignore' ? 'ignoredFeedback' : 'restoredFeedback'}`, count: result.changed_count });
      }
      onChanged();
      await load();
    } catch { if (current()) setActionError(true); }
    finally { submitting.current = false; if (current()) setBusy(false); }
  };

  const retryable = page?.items.filter((record) => record.retry_allowed) ?? [];
  return <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
    <SheetContent className="memory-theme-surface flex w-full max-w-full flex-col sm:max-w-2xl">
      <SheetHeader className="pr-16">
        <SheetTitle>{t('memory.processing.records.title')}</SheetTitle>
        <SheetDescription>{t('memory.processing.records.description')}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-wrap items-center gap-2 border-b border-border/50 px-6 pb-4">
        {(['failed', 'ignored'] as const).map((value) => <Button key={value} size="sm" variant={status === value ? 'secondary' : 'ghost'} aria-pressed={status === value} disabled={busy} onClick={() => {
          setStatus(value); setOffset(0); setFeedback(null); setActionError(false);
        }}>{t(`memory.processing.records.${value}`)}</Button>)}
        {filter.source || filter.reason ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setFilter({}); setOffset(0); }}>{t('memory.processing.records.showAll')}</Button> : null}
        <Button className="ml-auto" size="icon" variant="ghost" disabled={busy || loading} aria-label={t('memory.refresh')} onClick={() => void load()}><RefreshCw className="h-4 w-4" aria-hidden="true" /></Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {filter.source ? <p className="mb-3 text-xs text-muted-foreground">{getMemorySourceLabel(t, filter.source)}{filter.reason ? ` · ${t(`memory.processing.reasons.${filter.reason}.title`)}` : ''}</p> : null}
        {feedback ? <p role="status" className="mb-4 text-sm">{t(feedback.key, { count: feedback.count })}</p> : null}
        {actionError ? <p role="alert" className="mb-4 text-sm text-destructive">{t('memory.processing.records.actionFailed')}</p> : null}
        {loading ? <p role="status" className="text-sm text-muted-foreground">{t('memory.processing.details.loading')}</p> : loadError ? <div role="alert" className="space-y-2 text-sm">
          <p>{t('memory.processing.records.loadFailed')}</p><Button variant="outline" size="sm" onClick={() => void load()}>{t('common.retry')}</Button>
        </div> : page ? <>
          {page.items.some((record) => isContentRejection(record.reason)) ? <p className="mb-4 text-sm leading-6 text-muted-foreground">{t('memory.processing.records.contentNotice')}</p> : null}
          {page.items.length > 1 ? <div className="mb-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(status === 'failed' ? 'ignore' : 'restore', page.items)}>{t(`memory.processing.records.${status === 'failed' ? 'ignorePage' : 'restorePage'}`, { count: page.items.length })}</Button>
            {status === 'failed' && retryable.length > 0 ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act('retry', retryable)}>{t('memory.processing.records.retryPage', { count: retryable.length })}</Button> : null}
          </div> : null}
          {page.items.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">{t(`memory.processing.records.${status === 'failed' ? 'emptyFailed' : 'emptyIgnored'}`)}</p> : <ul className="divide-y divide-border/50">
            {page.items.map((record) => <li key={record.event_id} className="space-y-3 py-4">
              <div className="flex flex-wrap justify-between gap-1 text-xs text-muted-foreground">
                <span>{getMemorySourceLabel(t, record.source)}</span>
                {record.recorded_at !== null ? <span>{formatMemoryTimeRange(record.recorded_at, null, i18n.language)}</span> : null}
              </div>
              <p className="whitespace-pre-wrap break-words text-sm leading-6">{record.content ?? t('memory.processing.records.sourceUnavailable')}{record.content_truncated ? '…' : ''}</p>
              <p className="text-xs text-muted-foreground">{t(`memory.processing.reasons.${record.reason}.title`)}</p>
              <div className="flex flex-wrap gap-2">
                {record.content !== null ? <Button size="sm" variant="ghost" aria-expanded={openId === record.event_id} disabled={busy} onClick={() => setOpenId((value) => value === record.event_id ? null : record.event_id)}>{t(`memory.processing.records.${openId === record.event_id ? 'hideContent' : 'viewContent'}`)}</Button> : null}
                {status === 'failed' && record.retry_allowed ? <Button size="sm" variant="outline" disabled={busy} onClick={() => void act('retry', [record])}>{t('common.retry')}</Button> : null}
                <Button size="sm" variant={record.retry_allowed ? 'ghost' : 'outline'} disabled={busy} onClick={() => void act(status === 'failed' ? 'ignore' : 'restore', [record])}>{t(`memory.processing.records.${status === 'failed' ? 'ignore' : 'restore'}`)}</Button>
              </div>
              {openId === record.event_id ? <FailureSourceContent record={record} /> : null}
              <FailureTechnicalDetail error={record.error} time={formatMemoryTimeRange(record.last_failed_at, null, i18n.language)} />
            </li>)}
          </ul>}
        </> : null}
      </div>
      {page ? <div className="flex items-center justify-between gap-2 border-t border-border/50 px-6 py-4 text-xs text-muted-foreground">
        <span>{t('memory.processing.records.total', { count: page.total })}</span>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" disabled={busy || loading || offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>{t('memory.pagination.prev')}</Button>
          <span>{Math.floor(offset / PAGE_SIZE) + 1} / {Math.max(1, Math.ceil(page.total / PAGE_SIZE))}</span>
          <Button variant="ghost" size="sm" disabled={busy || loading || offset + PAGE_SIZE >= page.total} onClick={() => setOffset((value) => value + PAGE_SIZE)}>{t('memory.pagination.next')}</Button>
        </div>
      </div> : null}
    </SheetContent>
  </Sheet>;
}

function FailureSourceContent({ record }: { record: MemoryFailureRecord }) {
  const { t } = useTranslation('app');
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setContent(null);
    void memoryApi.getL2FailureRecords({ event_id: record.event_id, status: record.status, include_content: true, limit: 1 }).then((result) => {
      if (active) setContent(result.items.find((item) => item.event_id === record.event_id)?.content ?? null);
    }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [record.event_id, record.status, revision]);
  return <div className="rounded-lg bg-muted/40 p-3 text-sm leading-6">
    {loading ? <p role="status">{t('memory.processing.records.loadingContent')}</p> : error ? <div role="alert"><p>{t('memory.processing.records.loadFailed')}</p><Button size="sm" variant="ghost" onClick={() => setRevision((value) => value + 1)}>{t('common.retry')}</Button></div>
      : <blockquote className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words">{content ?? t('memory.processing.records.sourceUnavailable')}</blockquote>}
  </div>;
}
