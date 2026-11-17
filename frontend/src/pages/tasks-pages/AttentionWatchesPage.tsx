import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { attentionWatchesApi, type AttentionWatch, type WatchFields, type WatchMutation } from '@/api/modules/attentionWatches';
import { personalTasksApi } from '@/api/modules/personalTasks';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { MemoryEvidenceButton } from '@/components/memory/evidence/MemoryEvidenceButton';
import { useAppNavigate } from '@/hooks/useAppNavigate';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { getRuntimeGeneration } from '@/runtime/config';
import { getMemorySourceLabel } from '@/utils/memory-source-copy';
import { asEventHandler } from '@/utils/as-event-handler';
import { TasksPageFrame } from './TasksPageFrame';

const emptyFields = (): WatchFields => ({ title: '', condition: '', sources: [], expires_at: null, item_id: null });
type Editor = { watch: AttentionWatch | null; fields: WatchFields };

export const AttentionWatchesPage = () => {
  const { t } = useTranslation('app');
  const [params, setParams] = useSearchParams();
  const selected = params.get('watch');
  const linkedItem = params.get('item');
  const [offset, setOffset] = useState(0);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [deleting, setDeleting] = useState<AttentionWatch | null>(null);
  const [pending, setPending] = useState(false);
  const operationIds = useRef(new Map<string, string>());
  const generation = getRuntimeGeneration();
  const own = useRequestOwner(String(generation));
  const client = useQueryClient();
  const page = useQuery({ queryKey: ['attention-watches', generation, offset],
    queryFn: ({ signal }) => attentionWatchesApi.list(offset, signal) });
  const detail = useQuery({ queryKey: ['attention-watch', generation, selected], enabled: Boolean(selected),
    queryFn: ({ signal }) => attentionWatchesApi.get(selected ?? '', signal) });
  const refresh = async () => { await Promise.all([
    client.invalidateQueries({ queryKey: ['attention-watches', generation] }),
    client.invalidateQueries({ queryKey: ['attention-watch', generation] }),
  ]); };
  useCenterRefresh(refresh, ['personal_tasks', 'memory', 'notifications']);
  useEffect(() => {
    if (!linkedItem) return;
    const controller = new AbortController();
    void personalTasksApi.get(linkedItem, controller.signal).then(({ item }) => {
      if (!controller.signal.aborted) setEditor({ watch: null, fields: { ...emptyFields(), title: item.title, item_id: item.id } });
    }).catch(() => { if (!controller.signal.aborted) toast.error(t('attentionWatches.loadFailed')); });
    return () => controller.abort();
  }, [linkedItem, t]);

  const mutate = async (command: Omit<WatchMutation, 'request_id'>) => {
    if (pending) return;
    const current = own('mutation');
    const key = JSON.stringify(command);
    const requestId = operationIds.current.get(key) ?? crypto.randomUUID();
    operationIds.current.set(key, requestId);
    setPending(true);
    try {
      const result = await attentionWatchesApi.mutate({ ...command, request_id: requestId });
      if (!current() || generation !== getRuntimeGeneration()) return;
      setEditor(null); setDeleting(null);
      await setParams(result.watch ? { watch: result.watch.id } : {});
      await refresh();
    } catch {
      if (current()) { toast.error(t('attentionWatches.actionFailed')); await refresh(); }
    } finally { if (current()) setPending(false); }
  };
  const act = (watch: AttentionWatch, action: WatchMutation['action']) => mutate({ action, watch_id: watch.id, expected_version: watch.version });
  const items = page.isError ? [] : page.data?.items ?? [];
  const selectedExtra = !detail.isError && detail.data && !items.some((item) => item.id === detail.data.id) ? detail.data : null;
  return <TasksPageFrame onRefresh={asEventHandler(refresh)} refreshing={page.isFetching}
    loadError={page.isError || detail.isError ? t('attentionWatches.loadFailed') : null}
    actions={<Button onClick={() => setEditor({ watch: null, fields: emptyFields() })}>{t('attentionWatches.create')}</Button>}>
    <div className="mx-auto max-w-4xl space-y-4 p-5">
      <p className="text-sm leading-6 text-muted-foreground">{t('attentionWatches.scope')}</p>
      <details className="text-xs leading-5 text-muted-foreground"><summary className="cursor-pointer">{t('attentionWatches.limits')}</summary><p className="mt-2">{t('attentionWatches.budget')}</p></details>
      {page.isPending ? <p role="status">{t('attentionWatches.loading')}</p> : null}
      {!page.isError && page.data && !items.length && !selectedExtra ? <p className="py-10 text-center text-muted-foreground">{t('attentionWatches.empty')}</p> : null}
      {selectedExtra ? <WatchCard watch={selectedExtra} selected pending={pending} onAction={act} onEdit={(watch) => setEditor({ watch, fields: watch })} onDelete={setDeleting} onChanged={refresh} /> : null}
      {items.map((watch) => <WatchCard key={watch.id} watch={watch} selected={watch.id === selected} pending={pending}
        onAction={act} onEdit={(item) => setEditor({ watch: item, fields: item })} onDelete={setDeleting} onChanged={refresh} />)}
      <div className="flex gap-2"><Button variant="ghost" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('attentionWatches.previous')}</Button>
        <Button variant="ghost" disabled={page.data?.next_offset == null} onClick={() => setOffset(page.data?.next_offset ?? offset)}>{t('attentionWatches.next')}</Button></div>
    </div>
    {editor ? <WatchEditor editor={editor} sources={page.data?.sources ?? []} pending={pending}
      onClose={() => { if (!pending) { setEditor(null); if (linkedItem) void setParams({}); } }}
      onSave={(fields) => mutate({ action: editor.watch ? 'update' : 'create', watch_id: editor.watch?.id, expected_version: editor.watch?.version ?? 0, fields })} /> : null}
    <Dialog open={deleting !== null} onOpenChange={(open) => { if (!open && !pending) setDeleting(null); }}>
      <DialogContent><DialogHeader><DialogTitle>{t('attentionWatches.delete')}</DialogTitle><DialogDescription>{t('attentionWatches.deleteConfirm', { title: deleting?.title })}</DialogDescription></DialogHeader>
        <Button variant="destructive" disabled={pending} onClick={asEventHandler(async () => { if (deleting) await act(deleting, 'delete'); })}>{t('attentionWatches.delete')}</Button>
      </DialogContent>
    </Dialog>
  </TasksPageFrame>;
};

function WatchCard({ watch, selected, pending, onAction, onEdit, onDelete, onChanged }: {
  watch: AttentionWatch; selected: boolean; pending: boolean;
  onAction: (watch: AttentionWatch, action: WatchMutation['action']) => Promise<void>;
  onEdit: (watch: AttentionWatch) => void; onDelete: (watch: AttentionWatch) => void; onChanged: () => Promise<void>;
}) {
  const { t, i18n } = useTranslation('app');
  const navigate = useAppNavigate();
  const formatTime = (value: number) => new Date(value * 1000).toLocaleString(i18n.language);
  return <article className={`space-y-3 rounded-xl border p-4 ${selected ? 'border-primary' : 'border-border/60'}`}>
    <div className="flex justify-between gap-3"><h2 className="font-medium">{watch.title}</h2><span className="text-xs text-muted-foreground">{t(`attentionWatches.statuses.${watch.status}`)}</span></div>
    <p className="whitespace-pre-wrap text-sm">{watch.condition}</p>
    <p className="text-xs text-muted-foreground">{watch.sources.map((source) => getMemorySourceLabel(t, source)).join(' · ')}</p>
    <p className="text-xs text-muted-foreground">{watch.last_checked_at ? t('attentionWatches.lastChecked', { time: formatTime(watch.last_checked_at) }) : t('attentionWatches.notChecked')}
      {watch.expires_at ? ` · ${t('attentionWatches.expires', { time: formatTime(watch.expires_at) })}` : ''}</p>
    {watch.check_status === 'failed' || watch.check_status === 'invalidated' ? <p role="status" className="text-sm text-muted-foreground">{t(`attentionWatches.checks.${watch.check_status}`)}</p> : null}
    {watch.result ? <div className="space-y-2 rounded-lg bg-muted/50 p-3">
      <p className="whitespace-pre-wrap text-sm leading-6">{watch.result.summary}</p>
      {watch.result.next_step ? <p className="text-sm">{watch.result.next_step}</p> : null}
      <MemoryEvidenceButton target={{ title: watch.title, eventIds: watch.result.citations.map((citation) => citation.event_id) }} onChanged={asEventHandler(onChanged)} />
      <Button size="sm" variant="outline" onClick={() => navigate('/chat', { state: { suggestedDraft: t('attentionWatches.discussPrompt', { title: watch.title, result: watch.result?.summary }) } })}>{t('attentionWatches.discuss')}</Button>
    </div> : null}
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={pending} onClick={asEventHandler(() => onAction(watch, watch.status === 'active' ? 'pause' : 'resume'))}>{t(watch.status === 'active' ? 'attentionWatches.pause' : 'attentionWatches.resume')}</Button>
      <Button size="sm" variant="ghost" disabled={pending} onClick={() => onEdit(watch)}>{t('attentionWatches.edit')}</Button>
      {watch.status === 'active' || watch.status === 'paused' ? <Button size="sm" variant="ghost" disabled={pending} onClick={asEventHandler(() => onAction(watch, 'stop'))}>{t('attentionWatches.stop')}</Button> : null}
      <Button size="sm" variant="ghost" disabled={pending} onClick={() => onDelete(watch)}>{t('attentionWatches.delete')}</Button>
    </div>
  </article>;
}

function WatchEditor({ editor, sources, pending, onClose, onSave }: { editor: Editor; sources: string[]; pending: boolean; onClose: () => void; onSave: (fields: WatchFields) => Promise<void> }) {
  const { t } = useTranslation('app');
  const [fields, setFields] = useState<WatchFields>(() => ({ title: editor.fields.title, condition: editor.fields.condition,
    sources: editor.fields.sources, expires_at: editor.fields.expires_at, item_id: editor.fields.item_id }));
  const [expiry, setExpiry] = useState(() => {
    if (!fields.expires_at) return '';
    const date = new Date(fields.expires_at * 1000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  });
  const expiryValid = !expiry || Number.isFinite(new Date(expiry).getTime()) && new Date(expiry).getTime() > Date.now();
  const missingSource = fields.sources.some((source) => !sources.includes(source));
  const valid = fields.title.trim() && fields.condition.trim() && fields.sources.length > 0 && !missingSource && expiryValid;
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="max-h-[85vh] overflow-y-auto"><DialogHeader><DialogTitle>{t(editor.watch ? 'attentionWatches.edit' : 'attentionWatches.create')}</DialogTitle><DialogDescription>{t('attentionWatches.editorHint')}</DialogDescription></DialogHeader>
      <form className="space-y-4" onSubmit={asEventHandler(async (event) => { event.preventDefault(); if (valid && !pending) await onSave({ ...fields, expires_at: expiry ? new Date(expiry).getTime() / 1000 : null }); })}>
        <label className="block space-y-2 text-sm">{t('attentionWatches.fields.title')}<Input required maxLength={200} value={fields.title} onChange={(event) => setFields({ ...fields, title: event.target.value })} /></label>
        <label className="block space-y-2 text-sm">{t('attentionWatches.fields.condition')}<Textarea required maxLength={1500} value={fields.condition} onChange={(event) => setFields({ ...fields, condition: event.target.value })} /></label>
        <fieldset className="space-y-2"><legend className="mb-2 text-sm">{t('attentionWatches.fields.sources')}</legend>
          {[...new Set([...sources, ...fields.sources])].map((source) => <label key={source} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={fields.sources.includes(source)} onChange={(event) => setFields({ ...fields, sources: event.target.checked ? [...fields.sources, source] : fields.sources.filter((item) => item !== source) })} />{getMemorySourceLabel(t, source)}</label>)}
          {missingSource ? <p role="alert" className="text-sm text-destructive">{t('attentionWatches.sourceUnavailable')}</p> : null}
          {!sources.length ? <p className="text-sm text-muted-foreground">{t('attentionWatches.noSources')}</p> : null}
        </fieldset>
        <label className="block space-y-2 text-sm">{t('attentionWatches.fields.expires')}<Input type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} /></label>
        {!expiryValid ? <p role="alert" className="text-sm text-destructive">{t('attentionWatches.invalidExpiry')}</p> : null}
        {fields.item_id ? <p className="text-xs text-muted-foreground">{t('attentionWatches.linked')}</p> : null}
        <p className="text-xs leading-5 text-muted-foreground">{t('attentionWatches.budget')}</p>
        <Button type="submit" disabled={!valid || pending}>{t('attentionWatches.save')}</Button>
      </form>
    </DialogContent>
  </Dialog>;
}
