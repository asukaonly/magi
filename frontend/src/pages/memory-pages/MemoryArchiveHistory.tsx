import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryArchivesApi, type ArchiveSearchResult } from '@/api/modules/memoryArchives';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MemoryEvidenceButton } from '@/components/memory/evidence/MemoryEvidenceButton';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { APP_EVENTS } from '@/constants/events';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';

const PAGE_SIZE = 20;

export function MemoryArchiveHistory() {
  const { t, i18n } = useTranslation('app');
  const [draft, setDraft] = useState('');
  const [request, setRequest] = useState({ query: '', offset: 0 });
  const [result, setResult] = useState<ArchiveSearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const ownRequest = useRequestOwner(JSON.stringify(request));
  const load = useCallback(async () => {
    const current = ownRequest('archive');
    setLoading(true);
    setFailed(false);
    setResult(null);
    try {
      const response = await memoryArchivesApi.search(request.query, request.offset, PAGE_SIZE);
      if (current()) setResult(response);
    } catch { if (current()) setFailed(true); }
    finally { if (current()) setLoading(false); }
  }, [ownRequest, request]);
  useEffect(() => { void load(); return () => { ownRequest('archive'); }; }, [load, ownRequest]);
  useEffect(() => {
    const invalidate = (event: Event) => {
      const detail: unknown = event instanceof CustomEvent ? event.detail : null;
      if (event.type === APP_EVENTS.CENTER_STATE_CHANGED && detail && typeof detail === 'object'
        && 'resource' in detail && typeof detail.resource === 'string'
        && !['memory', 'chat'].includes(detail.resource)) return;
      ownRequest('archive');
      setResult(null);
      setFailed(false);
      setLoading(true);
    };
    const events = [APP_EVENTS.CENTER_STATE_CHANGED, APP_EVENTS.MEMORY_CLEAR_STARTED, APP_EVENTS.CENTER_MAINTENANCE];
    events.forEach((event) => window.addEventListener(event, invalidate));
    return () => events.forEach((event) => window.removeEventListener(event, invalidate));
  }, [ownRequest]);
  useCenterRefresh(load, ['memory', 'chat']);
  return <section className="space-y-4" aria-label={t('memory.recall.history.tab')}>
    <p className="text-sm text-muted-foreground">{t('memory.recall.history.description')}</p>
    <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); setRequest({ query: draft.trim(), offset: 0 }); }}>
      <Input value={draft} onChange={(event) => setDraft(event.target.value)} aria-label={t('memory.recall.history.placeholder')} placeholder={t('memory.recall.history.placeholder')} />
      <Button disabled={loading} type="submit">{t('common.search')}</Button>
    </form>
    {loading ? <p role="status">{t('memory.recall.searching')}</p> : null}
    {failed || result?.partial ? <div role="alert" className="space-y-2 rounded-lg border p-4">
      <p>{t(failed ? 'memory.recall.history.failed' : 'memory.recall.history.partial')}</p>
      <Button variant="outline" size="sm" onClick={() => { void load(); }}>{t('common.retry')}</Button>
    </div> : null}
    {result ? <>
      {!result.partial ? <p className="text-xs text-muted-foreground">{t('memory.recall.history.count', { count: result.total })}</p> : null}
      {result.items.length === 0 && !result.partial ? <p>{t('memory.recall.history.empty')}</p> : null}
      {result.items.map((item) => <article key={`${item.layer}:${item.record_id}`} className="space-y-2 rounded-lg border p-4">
        <h2 className="text-xs font-medium text-muted-foreground">{t(item.layer === 'l1' ? 'memory.recall.history.original' : 'memory.recall.history.summary')}</h2>
        <p className="whitespace-pre-wrap wrap-break-word text-sm leading-6">{item.content}</p>
        <p className="text-xs text-muted-foreground">{getMemorySourceLabel(t, item.source || item.event_type)} · {new Date(item.occurred_at * 1000).toLocaleString(i18n.language)}{item.period_end !== null ? ` – ${new Date(item.period_end * 1000).toLocaleString(i18n.language)}` : ''}</p>
        <p className="text-xs text-muted-foreground">{t('memory.recall.history.archivedAt', { time: new Date(item.archived_at * 1000).toLocaleString(i18n.language) })}</p>
        {item.layer === 'l3' ? <MemoryEvidenceButton target={{ title: item.content, eventIds: item.evidence_event_ids, source: item.source, occurredAt: item.occurred_at }} onChanged={() => { void load(); }} /> : null}
      </article>)}
      {result.total > PAGE_SIZE ? <div className="flex justify-between gap-2">
        <Button variant="outline" disabled={request.offset === 0} onClick={() => setRequest((value) => ({ ...value, offset: Math.max(0, value.offset - PAGE_SIZE) }))}>{t('memory.evidence.previous')}</Button>
        <Button variant="outline" disabled={request.offset + PAGE_SIZE >= result.total || request.offset + PAGE_SIZE > 10000} onClick={() => setRequest((value) => ({ ...value, offset: value.offset + PAGE_SIZE }))}>{t('memory.evidence.next')}</Button>
      </div> : null}
      {request.offset + PAGE_SIZE > 10000 && result.total > request.offset + PAGE_SIZE ? <p>{t('memory.recall.history.limitReached')}</p> : null}
    </> : null}
  </section>;
}
