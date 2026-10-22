import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { getRuntimeGeneration } from '@/runtime/config';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet';
import { personalTaskStatuses, personalTasksApi, type PersonalItem, type PersonalTaskFields, type PersonalTaskStatus } from '@/api/modules/personalTasks';

function localInput(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

interface Props {
  item: PersonalItem | null;
  projects: PersonalItem[];
  parentId?: string;
  onClose: () => void;
  onSaved: (item: PersonalItem) => void;
}

export function PersonalTaskEditor({item, projects, parentId, onClose, onSaved}: Props) {
  const {t} = useTranslation('app');
  const [title, setTitle] = useState(item?.title ?? '');
  const [body, setBody] = useState(item?.body_md ?? '');
  const [kind, setKind] = useState<'action' | 'project'>(item?.kind ?? 'action');
  const [status, setStatus] = useState<PersonalTaskStatus>(item?.status ?? 'active');
  const [parent, setParent] = useState(item?.parent_id ?? parentId ?? '');
  const [due, setDue] = useState(item?.due?.slice(0, 10) ?? '');
  const [defer, setDefer] = useState(item?.defer_until?.slice(0, 10) ?? '');
  const [reminder, setReminder] = useState(localInput(item?.remind_at));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [request, setRequest] = useState<{signature: string; id: string} | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const save = async () => {
    if (!title.trim() || pending) return;
    setPending(true);
    setError('');
    const generation = getRuntimeGeneration();
    try {
    const fields: PersonalTaskFields = {
      title: title.trim(), body_md: body, kind, status, parent_id: kind === 'project' ? null : parent || null,
      due: due === item?.due?.slice(0, 10) ? item.due : due || null,
      defer_until: defer === item?.defer_until?.slice(0, 10) ? item.defer_until : defer || null,
      remind_at: !['active', 'waiting'].includes(status) ? null : reminder === localInput(item?.remind_at) ? item?.remind_at ?? null : reminder ? new Date(reminder).toISOString() : null,
      timezone: item && (item.due || item.defer_until || item.remind_at) ? item.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    const signature = JSON.stringify(fields);
    const requestId = request?.signature === signature ? request.id : crypto.randomUUID();
    setRequest({signature, id: requestId});
      const result = await personalTasksApi.mutate({
        request_id: requestId, action: item ? 'update' : 'create', item_id: item?.id,
        expected_version: item?.version ?? 0, fields,
      });
      if (!mounted.current || generation !== getRuntimeGeneration()) return;
      if (!result.item) throw new Error('Saved personal item is unavailable');
      onSaved(result.item);
    } catch (err: unknown) {
      if (!mounted.current || generation !== getRuntimeGeneration()) return;
      const conflict = typeof err === 'object' && err !== null && 'status' in err && err.status === 409;
      setError(t(conflict ? 'personalTasks.conflict' : 'personalTasks.saveFailed'));
    } finally { if (mounted.current && generation === getRuntimeGeneration()) setPending(false); }
  };

  return <Sheet open onOpenChange={(open) => { if (!open && !pending) onClose(); }}>
    <SheetContent className="flex flex-col overflow-hidden sm:max-w-xl">
      <SheetHeader>
        <SheetTitle>{t(item ? 'personalTasks.edit' : 'personalTasks.create')}</SheetTitle>
        <SheetDescription>{t('personalTasks.editorHint')}</SheetDescription>
      </SheetHeader>
      <form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <fieldset disabled={pending} className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-4">
        <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-title">{t('personalTasks.title')}</label>
          <Input id="personal-title" autoFocus value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} required /></div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-kind">{t('personalTasks.kind')}</label>
            <select id="personal-kind" className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={kind}
              onChange={(e) => setKind(e.target.value === 'project' ? 'project' : 'action')}>
              <option value="action">{t('personalTasks.action')}</option><option value="project">{t('personalTasks.project')}</option>
            </select></div>
          <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-status">{t('personalTasks.status')}</label>
            <select id="personal-status" className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={status}
              onChange={(e) => { const found = personalTaskStatuses.find((value) => value === e.target.value); if (found) setStatus(found); }}>
              {personalTaskStatuses.map((value) => <option key={value} value={value}>{t(`personalTasks.statuses.${value}`)}</option>)}
            </select></div>
        </div>
        {kind === 'action' ? <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-parent">{t('personalTasks.project')}</label>
          <select id="personal-parent" className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={parent} onChange={(e) => setParent(e.target.value)}>
            <option value="">{t('personalTasks.noProject')}</option>
            {parent && !projects.some((project) => project.id === parent) ? <option value={parent}>{t('personalTasks.currentProject')}</option> : null}
            {projects.filter((project) => project.id !== item?.id).map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
          </select></div> : null}
        <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-body">{t('personalTasks.context')}</label>
          <Textarea id="personal-body" value={body} onChange={(e) => setBody(e.target.value)} rows={9} maxLength={100000} placeholder={t('personalTasks.contextHint')} /></div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-defer">{t('personalTasks.defer')}</label>
            <Input id="personal-defer" type="date" value={defer} onChange={(e) => setDefer(e.target.value)} /></div>
          <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-due">{t('personalTasks.due')}</label>
            <Input id="personal-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
        </div>
        <div className="space-y-2"><label className="text-sm font-medium" htmlFor="personal-reminder">{t('personalTasks.reminder')}</label>
          <Input id="personal-reminder" type="datetime-local" disabled={!['active', 'waiting'].includes(status)} value={reminder} onChange={(e) => setReminder(e.target.value)} />
          <p className="text-xs text-muted-foreground">{t('personalTasks.timeHint')}</p></div>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        </fieldset>
        <div className="flex shrink-0 justify-end gap-2 border-t px-6 py-4"><Button type="button" variant="outline" disabled={pending} onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" disabled={pending || !title.trim()}>{t(pending ? 'personalTasks.saving' : 'personalTasks.save')}</Button></div>
      </form>
    </SheetContent>
  </Sheet>;
}
