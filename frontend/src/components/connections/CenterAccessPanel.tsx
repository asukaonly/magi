import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { serverApi } from '@/api/modules/server';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getRuntimeConfig, resetRuntimeInitialization } from '@/runtime/config';
import { listConnectionProfiles } from '@/runtime/connections';

type Client = Awaited<ReturnType<typeof serverApi.clients>>[number];
type Grant = Awaited<ReturnType<typeof serverApi.pairingGrant>>;

/** Device authorization is managed on the connected center, independently of saved profiles. */
export function CenterAccessPanel() {
  const { t } = useTranslation('app');
  const [clients, setClients] = useState<Client[] | null>(null);
  const [currentClientId, setCurrentClientId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [grant, setGrant] = useState<Grant | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owner = useRef(0);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const actionPending = useRef(false);

  const load = useCallback(async () => {
    const request = ++owner.current;
    try {
      const [next, profiles] = await Promise.all([serverApi.clients(), listConnectionProfiles()]);
      if (request !== owner.current) return;
      const active = profiles.state.profiles.find((profile) => profile.id === getRuntimeConfig().profileId);
      setCurrentClientId(active?.mode === 'remote' ? active.client_id : null);
      setClients(next); setError(null);
    } catch {
      if (request === owner.current) setError(t('connections.access.loadFailed'));
    }
  }, [t]);
  useEffect(() => { void load(); return () => { owner.current += 1; }; }, [load]);
  useEffect(() => {
    if (!grant) return;
    const timer = window.setTimeout(() => { setGrant(null); setCopied(false); }, Math.max(0, grant.expires_at_ms - Date.now()));
    return () => window.clearTimeout(timer);
  }, [grant]);

  useCenterRefresh(load, !busy);

  const run = async (action: () => Promise<void>) => {
    if (actionPending.current) return;
    actionPending.current = true; setBusy(true); setError(null);
    const generation = owner.current;
    try { await action(); }
    catch { if (generation === owner.current) setError(t('connections.access.actionFailed')); }
    finally { actionPending.current = false; if (mounted.current) setBusy(false); }
  };
  const revoke = async (clientId: string) => {
    const generation = owner.current;
    await serverApi.revoke(clientId);
    if (generation !== owner.current) return;
    if (clientId === currentClientId) {
      resetRuntimeInitialization();
      window.location.replace('/');
      return;
    }
    setConfirming(null);
    setClients((current) => current?.map((client) => client.client_id === clientId ? { ...client, revoked_at_ms: Date.now() } : client) ?? null);
  };

  return <section className="space-y-3 border-t border-border pt-5">
    <h2 className="text-sm font-semibold">{t('connections.access.title')}</h2>
    <p className="text-xs leading-5 text-muted-foreground">{t('connections.access.description')}</p>
    {clients?.filter((client) => client.revoked_at_ms === null).map((client) => <div key={client.client_id} className="space-y-2 rounded-md border border-border p-3">
      <div className="flex items-center gap-3"><p className="min-w-0 flex-1 truncate text-sm">{client.name}{client.client_id === currentClientId ? ` · ${t('connections.access.thisDevice')}` : ''}</p>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirming(client.client_id)}>{t('connections.access.revoke')}</Button>
      </div>
      {confirming === client.client_id ? <div className="space-y-2">
        <p className="text-xs text-muted-foreground">{t(client.client_id === currentClientId ? 'connections.access.revokeSelfHint' : 'connections.access.revokeHint')}</p>
        <div className="flex gap-2"><Button size="sm" variant="destructive" disabled={busy} onClick={() => { void run(() => revoke(client.client_id)); }}>{t('connections.access.confirmRevoke')}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(null)}>{t('common.cancel')}</Button></div>
      </div> : null}
    </div>)}
    {clients && clients.every((client) => client.revoked_at_ms !== null) ? <p className="text-sm text-muted-foreground">{t('connections.access.empty')}</p> : null}
    {clients ? <Button variant="outline" disabled={busy} onClick={() => { void run(async () => {
      const generation = owner.current;
      const next = await serverApi.pairingGrant();
      if (generation === owner.current) { setGrant(next); setCopied(false); }
    }); }}>{t('connections.access.createCode')}</Button> : null}
    {grant ? <div className="space-y-2 rounded-md bg-muted p-3">
      <p className="text-xs text-muted-foreground">{t('connections.access.codeHint')}</p>
      <div className="flex gap-2"><Input aria-label={t('connections.pairingCode')} type="password" autoComplete="off" readOnly value={grant.pairing_token} />
        <Button variant="outline" disabled={busy} onClick={() => { void run(async () => { await navigator.clipboard.writeText(grant.pairing_token); setCopied(true); }); }}>{t(copied ? 'connections.access.copied' : 'connections.access.copy')}</Button></div>
    </div> : null}
    {!clients && !error ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p> : null}
    {error ? <div role="alert" className="space-y-2 text-sm text-destructive"><p>{error}</p><Button variant="outline" disabled={busy} onClick={() => { void load(); }}>{t('common.retry')}</Button></div> : null}
  </section>;
}
