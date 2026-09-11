import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Laptop, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { RemoteConnectionForm } from './RemoteConnectionForm';
import { useConnectionSetup } from './useConnectionSetup';

type PendingConnectionAction =
  | { kind: 'switch'; profileId: string; label: string }
  | { kind: 'pair'; label: string };

export function ConnectionPicker({
  hasUnsavedSettings = false,
}: {
  hasUnsavedSettings?: boolean;
}) {
  const { t } = useTranslation('app');
  const { profiles, draft, setDraft, busy, error, retry, connect, pair, forget } = useConnectionSetup();
  const [pendingAction, setPendingAction] = useState<PendingConnectionAction | null>(null);

  const confirmConnectionChange = async () => {
    const action = pendingAction;
    if (!action) return;
    if (action.kind === 'switch') {
      await connect(action.profileId);
    } else {
      await pair();
    }
    setPendingAction(null);
  };

  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm leading-7 text-muted-foreground">{t('connections.description')}</p>
      <div className="space-y-2">
        {profiles?.state.profiles.map((profile) => {
          const label = profile.mode === 'local' ? t('connections.local') : profile.name;
          const isActive = profile.id === profiles.state.active_profile_id;
          return (
            <div key={profile.id} className="flex items-center gap-3 rounded-md border border-border p-3">
              {profile.mode === 'local' ? <Laptop className="h-5 w-5 shrink-0" /> : <Server className="h-5 w-5 shrink-0" />}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium">{label}</p>
                  {isActive ? (
                    <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                      {t('connections.active')}
                    </span>
                  ) : null}
                </div>
                <p className="truncate text-xs text-muted-foreground">{profile.mode === 'local' ? t('connections.localDescription') : profile.api_base_url}</p>
              </div>
              {profile.mode === 'remote' && !isActive ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => { void forget(profile.id); }}>{t('connections.forget')}</Button> : null}
              {!isActive ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setPendingAction({ kind: 'switch', profileId: profile.id, label })}
                >
                  {profiles.state.active_profile_id ? t('connections.switch') : t('connections.connect')}
                </Button>
              ) : null}
            </div>
          );
        })}
        {!profiles && !error ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p> : null}
      </div>
      {profiles?.supports_remote ? <section className="space-y-3 border-t border-border pt-5">
        <h2 className="text-sm font-semibold">{t('connections.addRemote')}</h2>
        <RemoteConnectionForm
          draft={draft}
          onChange={setDraft}
          onSubmit={async () => setPendingAction({ kind: 'pair', label: draft.name.trim() })}
          busy={busy}
        />
      </section> : null}
      {error ? <div role="alert" className="space-y-2 text-sm text-destructive"><p className="break-words">{error}</p>{!profiles ? <Button variant="outline" onClick={retry}>{t('common.retry')}</Button> : null}</div> : null}

      <Dialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setPendingAction(null);
        }}
      >
        <DialogContent className="max-w-[440px]">
          <DialogHeader>
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300">
                <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <DialogTitle>
                  {t(pendingAction?.kind === 'pair' ? 'connections.confirmPairTitle' : 'connections.confirmSwitchTitle', {
                    name: pendingAction?.label ?? '',
                  })}
                </DialogTitle>
                <DialogDescription className="mt-2 leading-6">
                  {t(pendingAction?.kind === 'pair' ? 'connections.confirmPairDescription' : 'connections.confirmSwitchDescription')}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>
          {hasUnsavedSettings ? (
            <p role="alert" className="mx-6 rounded-md bg-amber-500/10 px-3 py-2 text-sm leading-6 text-amber-800 dark:text-amber-200">
              {t('connections.unsavedSettingsWarning')}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => setPendingAction(null)}>
              {t('common.cancel')}
            </Button>
            <Button type="button" disabled={busy} onClick={() => { void confirmConnectionChange(); }}>
              {t(busy
                ? 'connections.connecting'
                : pendingAction?.kind === 'pair'
                  ? 'connections.confirmPair'
                  : 'connections.confirmSwitch')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
