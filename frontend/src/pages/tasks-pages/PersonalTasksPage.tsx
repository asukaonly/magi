import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Check, ChevronRight, Folder, MessageCircle, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { personalTasksApi, type PersonalItem, type PersonalItemPage, type PersonalItemDetail, type PersonalTaskStatus, type PersonalTaskMutation } from '@/api/modules/personalTasks';
import { messagesApi } from '@/api/modules/messages';
import { DEFAULT_USER_ID } from '@/constants';
import { useConversationStore } from '@/stores/conversation-store';
import { useAppNavigate } from '@/hooks/useAppNavigate';
import { getRuntimeGeneration } from '@/runtime/config';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { MemoryEvidenceButton } from '@/components/memory/evidence/MemoryEvidenceButton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MarkdownBlock } from '@/components/ui/markdown-block';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { TasksPageFrame } from './TasksPageFrame';
import { PersonalTaskEditor } from './components/PersonalTaskEditor';

const views = ['next', 'inbox', 'waiting', 'someday', 'projects', 'review', 'all', 'completed', 'cancelled'] as const;

export const PersonalTasksPage = () => {
  const {t, i18n} = useTranslation('app');
  const navigate = useAppNavigate();
  const [params, setParams] = useSearchParams();
  const selected = params.get('item');
  const [view, setView] = useState<string>('next');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PersonalItemPage | null>(null);
  const [detail, setDetail] = useState<PersonalItemDetail | null>(null);
  const [projects, setProjects] = useState<PersonalItem[]>([]);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [detailError, setDetailError] = useState(false);
  const [editor, setEditor] = useState<{item: PersonalItem | null; parentId?: string} | null>(null);
  const [deleting, setDeleting] = useState<PersonalItem | null>(null);
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const [historyPending, setHistoryPending] = useState(false);
  const ownRequest = useRequestOwner(String(getRuntimeGeneration()));
  const operationIds = useRef(new Map<string, string>());
  const conversationIds = useRef(new Map<string, {create: string; turn: string}>());
  const selection = useRef(selected);
  selection.current = selected;
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  const select = (id: string | null) => { setNote(''); void setParams(id ? {item: id} : {}); };
  const formatTime = (value: string) => value.length === 10 ? value : new Date(value).toLocaleString(i18n.language);
  const mutate = async (command: Omit<PersonalTaskMutation, 'request_id'>) => {
    const key = JSON.stringify(command);
    const id = operationIds.current.get(key) ?? crypto.randomUUID();
    operationIds.current.set(key, id);
    const result = await personalTasksApi.mutate({...command, request_id: id});
    if (result.reminders_pending) toast.warning(t('personalTasks.reminderPending'));
    return result;
  };

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void personalTasksApi.list({view, search, offset}, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setPage(result); setError(false); }
    }).catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [view, search, offset, revision]);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      const items: PersonalItem[] = [];
      let next: number | null = 0;
      while (next !== null && !controller.signal.aborted) {
        const result = await personalTasksApi.list({view: 'projects', limit: 100, offset: next}, controller.signal);
        items.push(...result.items);
        next = result.next_offset;
      }
      if (!controller.signal.aborted) setProjects(items);
    };
    void load().catch(() => undefined);
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    const controller = new AbortController();
    setDetailError(false);
    void personalTasksApi.get(selected, controller.signal).then((result) => {
      if (!controller.signal.aborted) setDetail(result);
    }).catch(() => { if (!controller.signal.aborted) { setDetail(null); setDetailError(true); } });
    return () => controller.abort();
  }, [selected, revision]);

  useEffect(() => {
    const update = () => { if (document.visibilityState === 'visible') refresh(); };
    window.addEventListener('focus', update);
    const timer = window.setInterval(update, 15000);
    return () => { window.removeEventListener('focus', update); window.clearInterval(timer); };
  }, [refresh]);

  const updateItem = async (item: PersonalItem, status?: PersonalTaskStatus, progress?: string) => {
    if (pending) return;
    const generation = getRuntimeGeneration();
    const currentRequest = ownRequest('mutation');
    setPending(true);
    try {
      const result = await mutate({action: progress ? 'progress' : 'update',
        item_id: item.id, expected_version: item.version, fields: {status: status ?? item.status}, note: progress});
      if (!currentRequest() || generation !== getRuntimeGeneration()) return;
      const updated = result.item;
      if (updated) setDetail((previous) => previous?.item.id === updated.id ? {...previous, item: updated} : previous);
      if (selection.current === item.id) setNote('');
      refresh();
    } catch { if (currentRequest() && generation === getRuntimeGeneration()) toast.error(t('personalTasks.changeFailed')); }
    finally { if (currentRequest()) setPending(false); }
  };

  const remove = async () => {
    if (!deleting || pending) return;
    const generation = getRuntimeGeneration();
    const currentRequest = ownRequest('mutation');
    setPending(true);
    try {
      const result = await mutate({action: 'delete', item_id: deleting.id,
        expected_version: deleting.version, cascade: deleting.kind === 'project'});
      if (!currentRequest() || generation !== getRuntimeGeneration()) return;
      setDeleting(null);
      if (selection.current && result.deleted_ids.includes(selection.current)) select(null);
      refresh();
    } catch { if (currentRequest() && generation === getRuntimeGeneration()) toast.error(t('personalTasks.deleteFailed')); }
    finally { if (currentRequest()) setPending(false); }
  };

  const continueItem = async (item?: PersonalItem) => {
    if (pending) return;
    const generation = getRuntimeGeneration();
    const currentRequest = ownRequest('mutation');
    setPending(true);
    try {
      const key = item?.id ?? 'review';
      const ids = conversationIds.current.get(key) ?? {create: crypto.randomUUID(), turn: crypto.randomUUID()};
      conversationIds.current.set(key, ids);
      const created = await messagesApi.createNewSession(DEFAULT_USER_ID, ids.create);
      if (!created.success || !created.session_id) throw new Error('Conversation creation failed');
      const session = await messagesApi.getSession(DEFAULT_USER_ID, created.session_id);
      if (!currentRequest() || generation !== getRuntimeGeneration()) return;
      const sent = await messagesApi.sendMessage({session_id: session.session_id, user_id: DEFAULT_USER_ID,
        client_turn_id: ids.turn, personal_task_id: item?.id,
        message: item ? t('personalTasks.continuePrompt', {title: item.title}) : t('personalTasks.reviewPrompt')});
      if (!sent.success) throw new Error('Conversation turn was not accepted');
      if (!currentRequest() || generation !== getRuntimeGeneration()) return;
      useConversationStore.getState().upsertSession(session);
      useConversationStore.getState().setCurrentSessionId(session.session_id);
      navigate('/');
    } catch { if (currentRequest() && generation === getRuntimeGeneration()) toast.error(t('personalTasks.continueFailed')); }
    finally { if (currentRequest()) setPending(false); }
  };

  const openConversation = async (sessionId: string) => {
    const currentRequest = ownRequest('source');
    const generation = getRuntimeGeneration();
    try {
      const session = await messagesApi.getSession(DEFAULT_USER_ID, sessionId);
      if (!currentRequest() || generation !== getRuntimeGeneration()) return;
      useConversationStore.getState().upsertSession(session);
      useConversationStore.getState().setCurrentSessionId(session.session_id);
      navigate('/');
    } catch { if (currentRequest()) toast.error(t('personalTasks.sourceUnavailable')); }
  };

  const loadHistory = async () => {
    if (!detail || detail.next_history_offset === null || historyPending) return;
    const currentRequest = ownRequest('history');
    const generation = getRuntimeGeneration();
    setHistoryPending(true);
    try {
      const result = await personalTasksApi.get(detail.item.id, undefined, detail.next_history_offset);
      if (!currentRequest() || generation !== getRuntimeGeneration() || selection.current !== result.item.id) return;
      if (result.item.version !== detail.item.version) { refresh(); return; }
      setDetail((previous) => previous?.item.id === result.item.id && previous.item.version === result.item.version
        ? {...result, changes: [...previous.changes, ...result.changes]} : previous);
    } catch { if (currentRequest()) toast.error(t('personalTasks.loadFailed')); }
    finally { if (currentRequest()) setHistoryPending(false); }
  };

  const current = detail?.item.id === selected ? detail : null;
  return <TasksPageFrame onRefresh={refresh} refreshing={loading} actions={
    <Button onClick={() => setEditor({item: null})}><Plus className="mr-1 h-4 w-4" />{t('personalTasks.create')}</Button>
  } toolbar={<div className="flex flex-wrap gap-1">
    {views.map((value) => <Button key={value} size="sm" variant={view === value ? 'secondary' : 'ghost'}
      onClick={() => { setView(value); setOffset(0); }}>{t(`personalTasks.views.${value}`)}
      {page?.counts[value] ? <span className="ml-1 text-xs text-muted-foreground">{page.counts[value]}</span> : null}</Button>)}
  </div>}>
    <div className="mx-auto max-w-4xl space-y-5">
      <div><h1 className="text-xl font-semibold">{t('personalTasks.heading')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('personalTasks.description')}</p></div>
      <Input aria-label={t('personalTasks.search')} placeholder={t('personalTasks.search')} value={search}
        onChange={(e) => { setSearch(e.target.value); setOffset(0); }} />
      {view === 'inbox' ? <p className="rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">{t('personalTasks.inboxHint')}</p> : null}
      {view === 'review' ? <div className="flex items-center justify-between gap-3 rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground"><p>{t('personalTasks.reviewHint')}</p><Button disabled={pending} onClick={() => { void continueItem(); }}>{t('personalTasks.review')}</Button></div> : null}
      {error ? <p role="alert" className="text-sm text-destructive">{t('personalTasks.loadFailed')}</p> : null}
      {loading && !page ? <p role="status">{t('personalTasks.loading')}</p> : null}
      {page?.items.length === 0 && !error ? <div className="rounded-xl border border-dashed p-12 text-center text-muted-foreground">{t('personalTasks.empty')}</div> : null}
      <ul className="divide-y rounded-xl border">
        {page?.items.map((item) => <li key={item.id} className="flex items-start gap-3 p-4" data-testid="personal-task-row">
          <button type="button" aria-label={t(item.status === 'completed' ? 'personalTasks.reopen' : 'personalTasks.complete')}
            disabled={pending} onClick={() => { void updateItem(item, item.status === 'completed' ? 'active' : 'completed'); }}
            className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border hover:bg-muted">
            {item.status === 'completed' ? <Check className="h-4 w-4" /> : item.kind === 'project' ? <Folder className="h-3 w-3" /> : null}
          </button>
          <button type="button" className="min-w-0 flex-1 text-left" onClick={() => select(item.id)}>
            <span className={`block font-medium ${item.status === 'completed' ? 'text-muted-foreground line-through' : ''}`}>{item.title}</span>
            <span className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
              <span>{t(`personalTasks.statuses.${item.status}`)}</span>
              {item.origin === 'source' ? <span>{t('personalTasks.sourceSuggestion')}</span> : null}
              {item.due ? <span>{t('personalTasks.due')}: {formatTime(item.due)}</span> : null}
              {item.remind_at && item.reminder_synced_revision !== item.reminder_revision ? <span>{t('personalTasks.reminderPending')}</span> : null}
            </span>
          </button>
          <button type="button" aria-label={t('personalTasks.delete')} onClick={() => setDeleting(item)} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-destructive"><Trash2 className="h-4 w-4" /></button>
        </li>)}
      </ul>
      {page && page.total > 50 ? <div className="flex items-center justify-between text-sm"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('personalTasks.previous')}</Button>
        <span>{t('personalTasks.count', {count: page.total})}</span><Button variant="outline" disabled={page.next_offset === null} onClick={() => { if (page.next_offset !== null) setOffset(page.next_offset); }}>{t('personalTasks.next')}</Button></div> : null}
    </div>
    <Sheet open={selected !== null && editor === null} onOpenChange={(open) => { if (!open) select(null); }}>
      <SheetContent className="flex flex-col overflow-y-auto sm:max-w-2xl">
        <SheetHeader><SheetTitle>{current?.item.title ?? t('personalTasks.detail')}</SheetTitle><SheetDescription>{t('personalTasks.detailHint')}</SheetDescription></SheetHeader>
        {detailError ? <p role="alert" className="px-6 text-sm text-destructive">{t('personalTasks.detailFailed')}</p> : null}
        {current ? <div className="space-y-6 px-6 pb-6">
          <div className="flex flex-wrap gap-2">
            <Button disabled={pending} onClick={() => { void continueItem(current.item); }}><MessageCircle className="mr-2 h-4 w-4" />{t('personalTasks.continue')}</Button>
            <Button variant="outline" onClick={() => setEditor({item: current.item})}>{t('personalTasks.edit')}</Button>
            {current.item.status !== 'completed' ? <Button variant="outline" disabled={pending} onClick={() => { void updateItem(current.item, 'completed'); }}>{t('personalTasks.complete')}</Button> : null}
            <Button variant="ghost" onClick={() => setDeleting(current.item)}>{t('personalTasks.delete')}</Button>
          </div>
          <div className="flex flex-wrap gap-2">{(['active', 'waiting', 'someday', 'cancelled'] as const).map((status) => <Button key={status} size="sm" variant={current.item.status === status ? 'secondary' : 'ghost'} disabled={pending || current.item.status === status}
            onClick={() => { void updateItem(current.item, status); }}>{t(`personalTasks.statuses.${status}`)}</Button>)}</div>
          {current.item.origin === 'source' && current.item.status === 'inbox' ? <p className="rounded-lg bg-muted p-3 text-sm">{t('personalTasks.inboxHint')}</p> : null}
          <dl className="grid grid-cols-2 gap-2 text-sm">{(['due', 'defer_until', 'remind_at'] as const).map((field) => current.item[field] ? <div key={field}><dt className="text-muted-foreground">{t(`personalTasks.fields.${field}`)}</dt><dd>{formatTime(current.item[field])}</dd></div> : null)}</dl>
          {current.item.remind_at ? <p className="text-xs text-muted-foreground">{current.item.reminder_delivered_revision === current.item.reminder_revision ? t('personalTasks.reminderDelivered') : current.item.reminder_synced_revision !== current.item.reminder_revision ? t('personalTasks.reminderPending') : new Date(current.item.remind_at).getTime() < Date.now() ? t('personalTasks.reminderUnsent') : null}</p> : null}
          {current.item.body_md ? <MarkdownBlock>{current.item.body_md}</MarkdownBlock> : <p className="text-sm text-muted-foreground">{t('personalTasks.noContext')}</p>}
          {current.item.references.length ? <div className="space-y-2"><h2 className="font-medium">{t('personalTasks.sources')}</h2><div className="flex flex-wrap gap-2">{current.item.references.map((reference) => <span key={`${reference.kind}:${reference.id}`}>
            {reference.kind === 'memory' ? <MemoryEvidenceButton target={{title: reference.label, recordRef: {kind: 'event', id: reference.id}}} />
              : reference.kind === 'chat' && reference.session_id ? <Button variant="outline" size="sm" onClick={() => { if (reference.session_id) void openConversation(reference.session_id); }}>{reference.label || t('personalTasks.openConversation')}</Button>
                : <span className="text-xs text-muted-foreground">{reference.label || t(`personalTasks.referenceKinds.${reference.kind}`)}</span>}
          </span>)}</div></div> : null}
          {current.item.kind === 'project' ? <div className="space-y-2"><div className="flex items-center justify-between"><h2 className="font-medium">{t('personalTasks.actions')}</h2><Button size="sm" variant="ghost" onClick={() => setEditor({item: null, parentId: current.item.id})}>{t('personalTasks.addAction')}</Button></div>
            <p className="text-xs text-muted-foreground">{t('personalTasks.progressCount', {done: current.children.filter((child) => child.status === 'completed').length, total: current.children.length})}</p>
            {current.children.map((child) => <button type="button" key={child.id} onClick={() => select(child.id)} className="flex w-full items-center justify-between rounded-lg border p-3 text-left text-sm"><span>{child.title}</span><ChevronRight className="h-4 w-4" /></button>)}</div> : null}
          <div className="space-y-2"><h2 className="font-medium">{t('personalTasks.progress')}</h2>
            <Textarea aria-label={t('personalTasks.progress')} disabled={pending} placeholder={t('personalTasks.progressHint')} value={note} onChange={(e) => setNote(e.target.value)} maxLength={10000} />
            <Button variant="outline" disabled={pending || !note.trim()} onClick={() => { void updateItem(current.item, undefined, note.trim()); }}>{t('personalTasks.recordProgress')}</Button>
            <ol className="space-y-3 pt-3">{current.changes.map((change) => <li key={change.id} className="border-l-2 pl-3"><div className="flex gap-2 text-xs text-muted-foreground"><span>{t(`personalTasks.changes.${change.action}`, {defaultValue: t('personalTasks.changes.update')})}</span><span>{new Date(change.created_at * 1000).toLocaleString(i18n.language)}</span><span>{t(`personalTasks.actors.${change.actor}`, {defaultValue: change.actor})}</span></div>{Object.entries(change.action === 'create' ? {} : change.changes).map(([field, value]) => {
              const after = value && typeof value === 'object' && 'after' in value ? value.after : null;
              return <p key={field} className="mt-1 text-sm">{t(`personalTasks.fields.${field}`, {defaultValue: field})}{['body_md', 'parent_id'].includes(field) ? `: ${t('personalTasks.contextUpdated')}` : typeof after === 'string' ? `: ${field === 'status' ? t(`personalTasks.statuses.${after}`) : field === 'kind' ? t(`personalTasks.${after}`) : after}` : `: ${t('personalTasks.cleared')}`}</p>;
            })}{change.note ? <MarkdownBlock>{change.note}</MarkdownBlock> : null}</li>)}</ol>{current.next_history_offset !== null ? <Button variant="ghost" disabled={historyPending} onClick={() => { void loadHistory(); }}>{t('personalTasks.moreHistory')}</Button> : null}
          </div>
        </div> : null}
      </SheetContent>
    </Sheet>
    {editor ? <PersonalTaskEditor key={editor.item?.id ?? 'new'} item={editor.item} parentId={editor.parentId} projects={projects} onClose={() => setEditor(null)} onSaved={(item) => { setEditor(null); select(item.id); refresh(); }} /> : null}
    <Dialog open={deleting !== null} onOpenChange={(open) => { if (!open && !pending) setDeleting(null); }}><DialogContent><DialogHeader><DialogTitle>{t('personalTasks.deleteTitle')}</DialogTitle><DialogDescription>{t(deleting?.kind === 'project' ? 'personalTasks.deleteProjectHint' : 'personalTasks.deleteHint', {title: deleting?.title ?? ''})}</DialogDescription></DialogHeader><div className="flex justify-end gap-2"><Button variant="outline" disabled={pending} onClick={() => setDeleting(null)}>{t('common.cancel')}</Button><Button variant="destructive" disabled={pending} onClick={() => { void remove(); }}>{t('personalTasks.delete')}</Button></div></DialogContent></Dialog>
  </TasksPageFrame>;
};
