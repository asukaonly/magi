import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Laptop, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { activateConnection, forgetConnection, listConnectionProfiles, pairCenter, type ConnectionProfiles } from '@/runtime/connections';

export function ConnectionPicker() {
  const { t } = useTranslation('app');
  const [profiles, setProfiles] = useState<ConnectionProfiles | null>(null);
  const [address, setAddress] = useState('');
  const [name, setName] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    let current = true;
    listConnectionProfiles().then((result) => { if (current) setProfiles(result); }).catch(() => {
      if (current) setError(t('connections.loadFailed'));
    });
    return () => { current = false; mounted.current = false; };
  }, [revision, t]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await action(); }
    catch (failure) {
      if (mounted.current) setError(`${t('connections.failed')} ${failure instanceof Error ? failure.message : ''}`);
    } finally { if (mounted.current) setBusy(false); }
  };

  return <div className="space-y-6">
    <p className="text-sm text-muted-foreground">{t('connections.description')}</p>
    <div className="space-y-2">
      {profiles?.state.profiles.map((profile) => <div key={profile.id} className="flex items-center gap-3 rounded-md border border-border p-3">
        {profile.mode === 'local' ? <Laptop className="h-5 w-5 shrink-0" /> : <Server className="h-5 w-5 shrink-0" />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{profile.mode === 'local' ? t('connections.local') : profile.name}</p>
          <p className="truncate text-xs text-muted-foreground">{profile.mode === 'local' ? t('connections.localDescription') : profile.api_base_url}</p>
        </div>
        {profile.mode === 'remote' && profile.id !== profiles.state.active_profile_id ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => { void run(async () => { await forgetConnection(profile.id); setRevision((value) => value + 1); }); }}>{t('connections.forget')}</Button> : null}
        <Button size="sm" variant="outline" disabled={busy} onClick={() => { void run(() => activateConnection(profile.id)); }}>{t('connections.connect')}</Button>
      </div>)}
      {!profiles && !error ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p> : null}
    </div>
    {profiles?.supports_remote ? <form className="space-y-3 border-t border-border pt-5" onSubmit={(event) => {
      event.preventDefault();
      void run(async () => { const profile = await pairCenter(address, token, name); setToken(''); await activateConnection(profile.id); });
    }}>
      <h2 className="text-sm font-semibold">{t('connections.addRemote')}</h2>
      <p className="text-xs leading-5 text-muted-foreground">{t('connections.pairingHint')}</p>
      <label className="block space-y-1 text-sm"><span>{t('connections.name')}</span><Input value={name} onChange={(event) => setName(event.target.value)} maxLength={64} required disabled={busy} autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span>{t('connections.address')}</span><Input type="url" placeholder="https://magi.example.com" value={address} onChange={(event) => setAddress(event.target.value)} required disabled={busy} autoComplete="off" /></label>
      <label className="block space-y-1 text-sm"><span>{t('connections.pairingCode')}</span><Input type="password" value={token} onChange={(event) => setToken(event.target.value)} required disabled={busy} autoComplete="off" /></label>
      <p className="text-xs leading-5 text-muted-foreground">{t('connections.ownerAccess')}</p>
      <Button type="submit" disabled={busy || !name.trim() || !address.trim() || !token.trim()}>{t(busy ? 'connections.connecting' : 'connections.pair')}</Button>
    </form> : null}
    {error ? <div role="alert" className="space-y-2 text-sm text-destructive"><p className="break-words">{error}</p>{!profiles ? <Button variant="outline" onClick={() => { setError(null); setRevision((value) => value + 1); }}>{t('common.retry')}</Button> : null}</div> : null}
  </div>;
}
