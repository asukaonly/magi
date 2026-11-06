import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Laptop, MoreHorizontal, Plus, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { ConnectionRepairDialog } from './ConnectionRepairDialog';
import type { ConnectionProfile } from '@/runtime/connections';
import { isRemoteConnectionDraftComplete, RemoteConnectionForm } from './RemoteConnectionForm';
import { useConnectionSetup } from './useConnectionSetup';

type PendingConnectionAction =
  | { kind: 'switch'; profileId: string; label: string }
  | { kind: 'pair'; label: string };

export function ConnectionPicker({ hasUnsavedSettings = false }: { hasUnsavedSettings?: boolean }) {
  const { t } = useTranslation('app');
  const { profiles, draft, setDraft, busy, error, clearError, retry, connect, pair } = useConnectionSetup();
  const [managed, setManaged] = useState<{ profile: Extract<ConnectionProfile, { mode: 'remote' }>; action: 'repair' | 'forget' } | null>(null);
  const [addingRemote, setAddingRemote] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingConnectionAction | null>(null);
  const formId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const confirmationTitleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (pendingAction) confirmationTitleRef.current?.focus({ preventScroll: true });
    else if (addingRemote) dialogRef.current?.querySelector('input')?.focus({ preventScroll: true });
  }, [addingRemote, pendingAction]);

  const closeDialog = () => {
    if (busy) return;
    setAddingRemote(false);
    setPendingAction(null);
    setDraft((current) => ({ ...current, token: '' }));
    clearError();
  };

  const confirmConnectionChange = async () => {
    const action = pendingAction;
    if (!action) return;
    if (action.kind === 'switch') await connect(action.profileId);
    else await pair();
    setPendingAction(null);
  };

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 basis-64 space-y-1.5">
          <h2 className="text-[15px] font-semibold">{t('connections.savedTitle')}</h2>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('connections.description')}</p>
        </div>
        {profiles?.supports_remote ? <Button size="sm" className="shrink-0" disabled={busy} onClick={(event) => { triggerRef.current = event.currentTarget; clearError(); setAddingRemote(true); }}>
          <Plus className="mr-1.5 h-4 w-4" aria-hidden="true" />{t('connections.addRemote')}
        </Button> : null}
      </div>
      <div className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70">
        {profiles?.state.profiles.map((profile) => {
          const label = profile.mode === 'local' ? t('connections.local') : profile.name;
          const isActive = profile.id === profiles.state.active_profile_id;
          return (
            <div key={profile.id} className={`flex items-center gap-3 px-4 py-4 ${isActive ? 'bg-primary/5' : ''}`}>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-background/70 text-muted-foreground">
                {profile.mode === 'local' ? <Laptop className="h-5 w-5" aria-hidden="true" /> : <Server className="h-5 w-5" aria-hidden="true" />}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <p className="min-w-0 truncate text-sm font-medium">{label}</p>
                  {isActive ? <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{t('connections.active')}</span> : null}
                </div>
                <p className="truncate text-xs text-muted-foreground" title={profile.mode === 'remote' ? profile.api_base_url : undefined}>
                  {profile.mode === 'local' ? t('connections.localDescription') : profile.api_base_url}
                </p>
              </div>
              {!isActive ? <Button size="sm" variant="outline" className="shrink-0" disabled={busy}
                onClick={(event) => { triggerRef.current = event.currentTarget; clearError(); setPendingAction({ kind: 'switch', profileId: profile.id, label }); }}>
                {profiles.state.active_profile_id ? t('connections.switch') : t('connections.connect')}
              </Button> : null}
              {profile.mode === 'remote' ? <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon" variant="ghost" className="h-9 w-9 shrink-0" disabled={busy} aria-label={t('connections.manage', { name: label })}>
                    <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setManaged({ profile, action: 'repair' })}>{t('connections.repair.action')}</DropdownMenuItem>
                  {!isActive ? <DropdownMenuItem destructive onSelect={() => setManaged({ profile, action: 'forget' })}>{t('connections.forget')}</DropdownMenuItem> : null}
                </DropdownMenuContent>
              </DropdownMenu> : null}
            </div>
          );
        })}
        {!profiles && !error ? <p role="status" className="p-4 text-sm text-muted-foreground">{t('common.loading')}</p> : null}
      </div>
      {error && !addingRemote ? <div role="alert" className="space-y-2 text-sm text-destructive"><p className="wrap-break-word">{error}</p>{!profiles ? <Button variant="outline" onClick={retry}>{t('common.retry')}</Button> : null}</div> : null}

      {managed ? <ConnectionRepairDialog profile={managed.profile} action={managed.action}
        hasUnsavedSettings={hasUnsavedSettings}
        onClose={() => setManaged(null)} onSaved={() => { setManaged(null); retry(); }} /> : null}
      <Dialog open={addingRemote || pendingAction !== null} onOpenChange={(open) => { if (!open) closeDialog(); }}>
        <DialogContent ref={dialogRef} hideClose={busy} className="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-xl flex-col overflow-hidden"
          onOpenAutoFocus={(event) => {
            if (confirmationTitleRef.current) { event.preventDefault(); confirmationTitleRef.current.focus({ preventScroll: true }); }
          }}
          onCloseAutoFocus={(event) => { event.preventDefault(); triggerRef.current?.focus({ preventScroll: true }); }}>
          {pendingAction ? <>
            <DialogHeader className="shrink-0 pr-14">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <DialogTitle ref={confirmationTitleRef} tabIndex={-1} className="outline-hidden">{t(pendingAction.kind === 'pair' ? 'connections.confirmPairTitle' : 'connections.confirmSwitchTitle', { name: pendingAction.label })}</DialogTitle>
                  <DialogDescription className="mt-2 leading-6">
                    {t(pendingAction.kind === 'pair' ? 'connections.confirmPairDescription' : 'connections.confirmSwitchDescription')}
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>
            {hasUnsavedSettings ? <p role="alert" className="mx-6 mb-4 rounded-md bg-amber-500/10 px-3 py-2 text-sm leading-6 text-amber-800 dark:text-amber-200">{t('connections.unsavedSettingsWarning')}</p> : null}
            <DialogFooter className="shrink-0">
              <Button type="button" variant="ghost" disabled={busy} onClick={() => setPendingAction(null)}>{t('common.cancel')}</Button>
              <Button type="button" disabled={busy} onClick={() => { void confirmConnectionChange(); }}>
                {t(busy ? 'connections.connecting' : pendingAction.kind === 'pair' ? 'connections.confirmPair' : 'connections.confirmSwitch')}
              </Button>
            </DialogFooter>
          </> : <>
            <DialogHeader className="shrink-0 pr-14">
              <DialogTitle>{t('connections.addRemote')}</DialogTitle>
              <DialogDescription className="leading-6">{t('connections.pairingHint')}</DialogDescription>
            </DialogHeader>
            <div className="min-h-0 space-y-4 overflow-y-auto px-6 pb-6">
              <RemoteConnectionForm id={formId} draft={draft} onChange={setDraft} busy={busy} showSubmit={false} showPairingHint={false}
                onSubmit={async () => setPendingAction({ kind: 'pair', label: draft.name.trim() })} />
              {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
            </div>
            <DialogFooter className="shrink-0">
              <Button variant="ghost" disabled={busy} onClick={closeDialog}>{t('common.cancel')}</Button>
              <Button type="submit" form={formId} disabled={busy || !isRemoteConnectionDraftComplete(draft)}>{t(busy ? 'connections.connecting' : 'connections.pair')}</Button>
            </DialogFooter>
          </>}
        </DialogContent>
      </Dialog>
    </section>
  );
}
