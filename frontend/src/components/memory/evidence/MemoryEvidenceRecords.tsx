import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type L1Event } from '@/api/modules/memory';
import { manualEntriesApi, type ManualEntry } from '@/api/modules/manualEntries';
import { Button } from '@/components/ui/button';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { memoryEvidenceIds } from '@/domain/memory/evidence';

const PAGE_SIZE = 5;
type EvidenceRow = { id: string; state: 'ready'; record: L1Event } | { id: string; state: 'missing' | 'failed' };

export function MemoryEvidenceRecords({ eventIds, onChanged }: { eventIds: string[]; onChanged?: () => void }) {
  const { t, i18n } = useTranslation('app');
  const scope = JSON.stringify(memoryEvidenceIds(eventIds));
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<EvidenceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [forgettingId, setForgettingId] = useState<string | null>(null);
  const [forgetFailed, setForgetFailed] = useState(false);
  const [preparingId, setPreparingId] = useState<string | null>(null);
  const [ownerEntry, setOwnerEntry] = useState<ManualEntry | null>(null);
  const [ownerUnavailableId, setOwnerUnavailableId] = useState<string | null>(null);
  const [prepareFailedId, setPrepareFailedId] = useState<string | null>(null);
  const ownRequest = useRequestOwner(`${scope}:${page}`);
  const ids = memoryEvidenceIds(JSON.parse(scope));
  const load = useCallback(async () => {
    const current = ownRequest('evidence');
    const keys = memoryEvidenceIds(JSON.parse(scope)).slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    setLoading(true);
    setRows([]);
    const results = await Promise.allSettled(keys.map((eventId) => memoryApi.getL1Events({ event_id: eventId, limit: 1 })));
    if (!current()) return;
    setRows(results.map((result, index): EvidenceRow => {
      const id = keys[index];
      if (result.status === 'rejected') return { id, state: 'failed' };
      const record = result.value.items.find((item) => item.event_id === id);
      return record ? { id, state: 'ready', record } : { id, state: 'missing' };
    }));
    setLoading(false);
  }, [ownRequest, scope, page]);
  useEffect(() => {
    void load();
    return () => { ownRequest('evidence'); };
  }, [load, ownRequest]);
  useEffect(() => { setPage(0); setConfirmId(null); setForgetFailed(false); setForgettingId(null); setPreparingId(null); setOwnerEntry(null); setOwnerUnavailableId(null); setPrepareFailedId(null); }, [scope]);

  const prepareForget = async (record: L1Event) => {
    if (preparingId || forgettingId) return;
    setForgetFailed(false);
    setPrepareFailedId(null);
    setOwnerEntry(null);
    if (record.source !== 'manual_entry') { setConfirmId(record.event_id); return; }
    if (!record.source_item_id) { setOwnerUnavailableId(record.event_id); return; }
    const current = ownRequest('owner');
    setPreparingId(record.event_id);
    try {
      const entry = await manualEntriesApi.get(record.source_item_id);
      if (!current()) return;
      if (entry.l1_event_id !== record.event_id || entry.deleted_at !== null) {
        setOwnerUnavailableId(record.event_id);
        return;
      }
      setOwnerEntry(entry);
      setConfirmId(record.event_id);
    } catch { if (current()) setPrepareFailedId(record.event_id); }
    finally { if (current()) setPreparingId(null); }
  };

  const forget = async (record: L1Event) => {
    if (forgettingId) return;
    const id = record.event_id;
    const current = ownRequest('forget');
    setForgettingId(id);
    setForgetFailed(false);
    try {
      if (record.source === 'manual_entry') {
        if (!ownerEntry || ownerEntry.entry_id !== record.source_item_id || ownerEntry.l1_event_id !== id) {
          setOwnerUnavailableId(id);
          setConfirmId(null);
          return;
        }
        await manualEntriesApi.remove(ownerEntry.entry_id);
      } else {
        await memoryApi.deleteL1Event(id);
      }
      if (!current()) return;
      setConfirmId(null);
      setRows((previous) => previous.map((row) => row.id === id ? { id, state: 'missing' } : row));
      onChanged?.();
    } catch {
      if (current()) setForgetFailed(true);
    } finally {
      if (current()) setForgettingId(null);
    }
  };

  return <div className="space-y-4 text-sm">
    {loading ? <p role="status">{t('memory.identity.loading')}</p> : null}
    {!loading && ids.length === 0 ? <p className="text-muted-foreground">{t('memory.evidence.noReferences')}</p> : null}
    {rows.map((row, index) => <section key={row.id} className="space-y-2 rounded-lg border p-3">
      <h3 className="text-xs font-medium text-muted-foreground">{t('memory.evidence.sourceNumber', { number: page * PAGE_SIZE + index + 1 })}</h3>
      {row.state === 'ready' ? <>
        <blockquote className="whitespace-pre-wrap wrap-break-word border-l-2 pl-3">{row.record.content}</blockquote>
        <p className="text-xs text-muted-foreground">{getMemorySourceLabel(t, row.record.source || row.record.event_type)} · {new Date(row.record.timestamp * 1000).toLocaleString(i18n.language)}</p>
        {confirmId === row.id ? <div className="space-y-2 rounded-md bg-muted p-3">
          <p>{t(row.record.source === 'manual_entry' ? 'memory.governance.destructiveConfirm.manualEntryDescription' : row.record.source === 'chat' ? 'memory.governance.destructiveConfirm.chatEventDescription' : 'memory.evidence.forgetConfirm')}</p>
          {ownerEntry ? <blockquote className="whitespace-pre-wrap wrap-break-word border-l-2 pl-3">{ownerEntry.body}</blockquote> : null}
          <div className="flex gap-2">
            <Button size="sm" variant="destructive" disabled={Boolean(forgettingId)} onClick={() => { void forget(row.record); }}>{t(row.record.source === 'manual_entry' ? 'memory.governance.destructiveConfirm.confirmManualEntry' : row.record.source === 'chat' ? 'memory.governance.destructiveConfirm.confirmChatEvent' : 'memory.evidence.confirmForget')}</Button>
            <Button size="sm" variant="ghost" disabled={Boolean(forgettingId)} onClick={() => setConfirmId(null)}>{t('common.cancel')}</Button>
          </div>
          {forgetFailed ? <p role="alert">{t('memory.evidence.forgetFailed')}</p> : null}
        </div> : row.record.source === 'manual_entry' && (!row.record.source_item_id || ownerUnavailableId === row.id) ? <p className="text-xs text-muted-foreground">{t('memory.evidence.ownerUnavailable')}</p> : <Button size="sm" variant="ghost" disabled={Boolean(preparingId || forgettingId)} onClick={() => { void prepareForget(row.record); }}>{t(row.record.source === 'chat' ? 'memory.governance.destructiveConfirm.confirmChatEvent' : 'memory.evidence.forgetSource')}</Button>}
        {prepareFailedId === row.id ? <p role="alert">{t('memory.evidence.loadFailed')}</p> : null}
      </> : <p role={row.state === 'failed' ? 'alert' : undefined} className="text-muted-foreground">{t(row.state === 'failed' ? 'memory.evidence.loadFailed' : 'memory.evidence.unavailable')}</p>}
    </section>)}
    {rows.some((row) => row.state === 'failed') ? <Button variant="outline" size="sm" onClick={() => { void load(); }}>{t('common.retry')}</Button> : null}
    {ids.length > PAGE_SIZE ? <div className="flex items-center justify-between gap-2">
      <Button variant="outline" size="sm" disabled={page === 0 || loading || Boolean(forgettingId || preparingId)} onClick={() => setPage((value) => value - 1)}>{t('memory.evidence.previous')}</Button>
      <span className="text-xs text-muted-foreground">{t('memory.evidence.page', { page: page + 1, pages: Math.ceil(ids.length / PAGE_SIZE), count: ids.length })}</span>
      <Button variant="outline" size="sm" disabled={(page + 1) * PAGE_SIZE >= ids.length || loading || Boolean(forgettingId || preparingId)} onClick={() => setPage((value) => value + 1)}>{t('memory.evidence.next')}</Button>
    </div> : null}
  </div>;
}
