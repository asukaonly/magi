import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Folder, File, ArrowUp, Home } from 'lucide-react';
import { centerFilesApi, type CenterDirectory } from '@/api/modules/centerFiles';
import { finishCenterPath, useCenterPathPickerStore, type CenterPathRequest } from '@/stores/center-path-picker';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function CenterPathPicker({ request }: { request: CenterPathRequest }) {
  const { t } = useTranslation('app');
  const [directory, setDirectory] = useState<CenterDirectory | null>(null);
  const [path, setPath] = useState(request.defaultPath ?? '');
  const [prefix, setPrefix] = useState('');
  const [showHidden, setShowHidden] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const generation = useRef(0);
  const initial = useRef(request.defaultPath);

  const load = useCallback(async (target?: string, after?: string, filter = '', hidden = false) => {
    const owner = ++generation.current;
    setBusy(true); setFailed(false); setSelected(null);
    try {
      const response = await centerFilesApi.browse({ path: target, after, prefix: filter, showHidden: hidden, directoriesOnly: request.kind === 'directory', resolveFile: request.kind === 'file' });
      if (owner !== generation.current) return;
      setDirectory(previous => after && previous?.path === response.path
        ? { ...response, entries: [...previous.entries, ...response.entries] } : response);
      setPath(response.path); setSelected(response.selected_file);
    } catch {
      if (owner === generation.current) setFailed(true);
    } finally {
      if (owner === generation.current) setBusy(false);
    }
  }, [request.kind]);

  useEffect(() => {
    void load(initial.current);
    return () => { generation.current += 1; };
  }, [load]);

  const navigate = (target?: string) => {
    setPrefix(''); setSelected(null);
    void load(target, undefined, '', showHidden);
  };
  const create = async () => {
    if (!directory || !name.trim()) return;
    const owner = ++generation.current;
    setBusy(true); setFailed(false);
    try {
      const response = await centerFilesApi.createDirectory(directory.path, name.trim());
      if (owner !== generation.current) return;
      setDirectory(response); setPath(response.path); setSelected(null); setPrefix(''); setName('');
    } catch {
      if (owner === generation.current) setFailed(true);
    } finally {
      if (owner === generation.current) setBusy(false);
    }
  };
  const choice = request.kind === 'directory' ? directory?.path : selected;
  return (
    <Dialog open onOpenChange={open => { if (!open) finishCenterPath(request.id); }}>
      <DialogContent className="max-w-2xl" >
        <DialogHeader>
          <DialogTitle>{t(request.kind === 'directory' ? 'centerFiles.chooseDirectory' : 'centerFiles.chooseFile')}</DialogTitle>
          <DialogDescription>{t('centerFiles.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 px-6 pb-4">
          <form className="flex gap-2" onSubmit={event => { event.preventDefault(); navigate(path || undefined); }}>
            <Button type="button" variant="outline" size="icon" disabled={busy} aria-label={t('centerFiles.home')} onClick={() => navigate()}><Home className="h-4 w-4" /></Button>
            <Button type="button" variant="outline" size="icon" disabled={busy || !directory?.parent} aria-label={t('centerFiles.parent')} onClick={() => { if (directory?.parent) navigate(directory.parent); }}><ArrowUp className="h-4 w-4" /></Button>
            <Input aria-label={t('centerFiles.path')} value={path} onChange={event => setPath(event.target.value)} />
            <Button type="submit" variant="outline" disabled={busy}>{t('centerFiles.go')}</Button>
          </form>
          <form className="flex items-center gap-2" onSubmit={event => { event.preventDefault(); void load(directory?.path, undefined, prefix, showHidden); }}>
            <Input aria-label={t('centerFiles.filter')} placeholder={t('centerFiles.filter')} value={prefix} onChange={event => setPrefix(event.target.value)} />
            <Button type="submit" variant="outline" disabled={busy}>{t('centerFiles.filterAction')}</Button>
            <label className="flex shrink-0 items-center gap-2 text-sm"><input type="checkbox" checked={showHidden} disabled={busy} onChange={event => { setShowHidden(event.target.checked); void load(directory?.path, undefined, prefix, event.target.checked); }} />{t('centerFiles.hidden')}</label>
          </form>
          {failed && <p role="alert" className="text-sm text-destructive">{t('centerFiles.loadFailed')}</p>}
          <div className="h-64 overflow-auto rounded-md border" aria-busy={busy}>
            {directory?.entries.filter(entry => request.kind === 'file' || entry.kind === 'directory').map(entry => (
              <button key={entry.path} type="button" disabled={busy} className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted ${selected === entry.path ? 'bg-muted' : ''}`} onClick={() => entry.kind === 'directory' ? navigate(entry.path) : setSelected(entry.path)}>
                {entry.kind === 'directory' ? <Folder className="h-4 w-4 shrink-0" /> : <File className="h-4 w-4 shrink-0" />}
                <span className="truncate">{entry.name}</span>
              </button>
            ))}
            {!busy && directory?.entries.length === 0 && <p className="p-4 text-sm text-muted-foreground">{t('centerFiles.empty')}</p>}
            {directory?.next_after && <Button className="m-2" variant="ghost" disabled={busy} onClick={() => { void load(directory.path, directory.next_after ?? undefined, prefix, showHidden); }}>{t('centerFiles.more')}</Button>}
          </div>
          <form className="flex gap-2" onSubmit={event => { event.preventDefault(); void create(); }}>
            <Input aria-label={t('centerFiles.newFolder')} placeholder={t('centerFiles.newFolder')} value={name} onChange={event => setName(event.target.value)} />
            <Button type="submit" variant="outline" disabled={busy || !directory || !name.trim()}>{t('centerFiles.create')}</Button>
          </form>
          <p className="break-all text-xs text-muted-foreground">{choice}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => finishCenterPath(request.id)}>{t('common.cancel')}</Button>
          <Button disabled={busy || failed || !choice || path !== directory?.path} onClick={() => { if (choice) finishCenterPath(request.id, choice); }}>{t('centerFiles.select')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CenterPathPickerHost() {
  const request = useCenterPathPickerStore(state => state.request);
  return request ? <CenterPathPicker key={request.id} request={request} /> : null;
}
