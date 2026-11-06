import { PairingCodeDialog } from './PairingCodeDialog';
import { MonitorSmartphone } from 'lucide-react';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { serverApi } from '@/api/modules/server';
import { Button } from '@/components/ui/button';
import { getRuntimeConfig, resetRuntimeInitialization } from '@/runtime/config';
import { listConnectionProfiles } from '@/runtime/connections';

type Client = Awaited<ReturnType<typeof serverApi.clients>>[number];

/** Device authorization is managed on the connected center, independently of saved profiles. */
export function CenterAccessPanel() {
  const { t } = useTranslation('app');
  const [clients, setClients] = useState<Client[] | null>(null);
  const [currentClientId, setCurrentClientId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
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


  useCenterRefresh(load, ["server"], !busy);

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

  return <section className="space-y-4 border-t border-border/60 pt-8">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1 basis-64 space-y-1.5">
        <h2 className="text-[15px] font-semibold">{t('connections.access.title')}</h2>
        <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('connections.access.description')}</p>
      </div>
      <PairingCodeDialog disabled={!clients || busy} />
    </div>
    {clients?.filter((client) => client.revoked_at_ms === null).map((client) => <div key={client.client_id} className="space-y-2 rounded-xl bg-muted/25 px-4 py-3">
      <div className="flex items-center gap-3"><MonitorSmartphone className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" /><p className="min-w-0 flex-1 truncate text-sm">{client.name}{client.client_id === currentClientId ? ` · ${t('connections.access.thisDevice')}` : ''}</p>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirming(client.client_id)}>{t('connections.access.revoke')}</Button>
      </div>
      <p className="break-all text-xs text-muted-foreground">{t(client.role === 'collector' ? 'connections.access.collectorRole' : 'connections.access.adminRole')}{client.collector_scope ? ` · ${client.collector_scope.source_type} · ${client.collector_scope.connection_id}` : ''}</p>
      {confirming === client.client_id ? <div className="space-y-2">
        <p className="text-xs text-muted-foreground">{t(client.client_id === currentClientId ? 'connections.access.revokeSelfHint' : 'connections.access.revokeHint')}</p>
        <div className="flex gap-2"><Button size="sm" variant="destructive" disabled={busy} onClick={() => { void run(() => revoke(client.client_id)); }}>{t('connections.access.confirmRevoke')}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(null)}>{t('common.cancel')}</Button></div>
      </div> : null}
    </div>)}
    {clients && clients.every((client) => client.revoked_at_ms !== null) ? <p className="text-sm text-muted-foreground">{t('connections.access.empty')}</p> : null}
    {!clients && !error ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p> : null}
    {error ? <div role="alert" className="space-y-2 text-sm text-destructive"><p>{error}</p><Button variant="outline" disabled={busy} onClick={() => { void load(); }}>{t('common.retry')}</Button></div> : null}
  </section>;
}
