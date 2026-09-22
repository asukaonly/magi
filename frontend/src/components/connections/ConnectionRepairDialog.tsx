import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { activateConnection, forgetConnection, readConnectionQueue, repairConnection, type ConnectionProfile } from '@/runtime/connections';
import { getErrorMessage } from '@/utils/error-handler';
import { connectionErrorKey } from './connectionErrors';

type RemoteProfile = Extract<ConnectionProfile, { mode: 'remote' }>;

/** Repair retains a saved destination; replacing authorization requires an explicit queue decision. */
export function ConnectionRepairDialog({ profile, action, hasUnsavedSettings, onClose, onSaved }: {
  profile: RemoteProfile; action: 'repair' | 'forget'; hasUnsavedSettings: boolean;
  onClose: () => void; onSaved: () => void;
}) {
  const { t } = useTranslation('app');
  const [address, setAddress] = useState(profile.api_base_url);
  const [name, setName] = useState(profile.name);
  const [token, setToken] = useState('');
  const [deviceName, setDeviceName] = useState('');
  const [queued, setQueued] = useState<number | null>(null);
  const [discard, setDiscard] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const forgetting = action === 'forget';
  const requiresDiscard = (forgetting || Boolean(token.trim())) && (queued ?? 0) > 0;
  useEffect(() => {
    let current = true;
    setQueued(null); setError(null);
    void readConnectionQueue(profile.id).then((queue) => {
      if (current) setQueued(queue.pending + queue.failed);
    }).catch(() => { if (current) setError(t('connections.repair.queueFailed')); });
    return () => { current = false; };
  }, [profile.id, attempt, t]);
  const submit = async () => {
    if (inFlight.current || queued === null || (requiresDiscard && !discard)) return;
    inFlight.current = true;
    setBusy(true); setError(null);
    try {
      if (forgetting) await forgetConnection(profile.id, discard);
      else {
        await repairConnection({ profileId: profile.id, address: address.trim(), name: name.trim(),
          pairingToken: token.trim() || null, deviceName: deviceName.trim(), discardPending: discard });
        if (!mounted.current) return;
        await activateConnection(profile.id);
      }
      if (mounted.current) onSaved();
    } catch (failure) {
      if (!mounted.current) return;
      const detail = getErrorMessage(failure) ?? (typeof failure === 'string' ? failure : '');
      const key = connectionErrorKey(detail);
      setError(key ? t(key) : `${t('connections.failed')} ${detail}`.trim());
      // A queue may grow while the dialog is open. Keep the user's fields and
      // demand fresh confirmation rather than silently dropping new records.
      if (detail === 'connection_has_pending_data') {
        setDiscard(false);
        const queue = await readConnectionQueue(profile.id).catch(() => null);
        if (mounted.current) setQueued(queue ? queue.pending + queue.failed : null);
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  const invalid = !forgetting && (!address.trim() || !name.trim() || (Boolean(token.trim()) && !deviceName.trim()));
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
    <DialogContent className="max-w-xl">
      <DialogHeader>
        <DialogTitle>{t(forgetting ? 'connections.repair.forgetTitle' : 'connections.repair.title', { name: profile.name })}</DialogTitle>
        <DialogDescription>{t(forgetting ? 'connections.repair.forgetDescription' : 'connections.repair.description')}</DialogDescription>
      </DialogHeader>
      <div className="space-y-4 px-6">
        {!forgetting ? <>
          <label className="block space-y-2 text-sm"><span>{t('connections.address')}</span><Input value={address} onChange={(event) => setAddress(event.target.value)} disabled={busy} autoComplete="off" /></label>
          <label className="block space-y-2 text-sm"><span>{t('connections.name')}</span><Input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} maxLength={64} /></label>
          <label className="block space-y-2 text-sm"><span>{t('connections.repair.code')}</span><Input type="password" value={token} onChange={(event) => { setToken(event.target.value); setDiscard(false); }} disabled={busy} autoComplete="off" /></label>
          <p className="text-xs leading-5 text-muted-foreground">{t('connections.repair.codeHint')}</p>
          {token.trim() ? <label className="block space-y-2 text-sm"><span>{t('connections.deviceName')}</span><Input value={deviceName} onChange={(event) => setDeviceName(event.target.value)} disabled={busy} maxLength={64} /></label> : null}
          {hasUnsavedSettings ? <p className="text-sm text-destructive">{t('connections.unsavedSettingsWarning')}</p> : null}
        </> : null}
        <p role="status" className="text-sm">{queued === null ? t('common.loading') : t('connections.repair.queued', { count: queued })}</p>
        {requiresDiscard ? <label className="flex items-start gap-3 rounded-md border border-destructive/30 p-3 text-sm leading-6">
          <input type="checkbox" className="mt-1.5" checked={discard} disabled={busy} onChange={(event) => setDiscard(event.target.checked)} />
          <span>{t('connections.repair.discard', { count: queued ?? 0 })}</span>
        </label> : null}
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        {queued === null && error ? <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>{t('common.retry')}</Button> : null}
      </div>
      <DialogFooter>
        <Button variant="ghost" disabled={busy} onClick={onClose}>{t('common.cancel')}</Button>
        <Button disabled={busy || queued === null || invalid || (requiresDiscard && !discard)} onClick={() => { void submit(); }}>
          {t(busy ? 'connections.connecting' : forgetting ? 'connections.repair.forgetConfirm' : 'connections.repair.save')}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
