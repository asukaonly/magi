import { useTranslation } from 'react-i18next';
import { Laptop, Server } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { RemoteConnectionForm } from './RemoteConnectionForm';
import { useConnectionSetup } from './useConnectionSetup';

export function ConnectionPicker() {
  const { t } = useTranslation('app');
  const { profiles, draft, setDraft, busy, error, retry, connect, pair, forget } = useConnectionSetup();

  return <div className="space-y-6">
    <p className="text-sm text-muted-foreground">{t('connections.description')}</p>
    <div className="space-y-2">
      {profiles?.state.profiles.map((profile) => <div key={profile.id} className="flex items-center gap-3 rounded-md border border-border p-3">
        {profile.mode === 'local' ? <Laptop className="h-5 w-5 shrink-0" /> : <Server className="h-5 w-5 shrink-0" />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{profile.mode === 'local' ? t('connections.local') : profile.name}</p>
          <p className="truncate text-xs text-muted-foreground">{profile.mode === 'local' ? t('connections.localDescription') : profile.api_base_url}</p>
        </div>
        {profile.mode === 'remote' && profile.id !== profiles.state.active_profile_id ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => { void forget(profile.id); }}>{t('connections.forget')}</Button> : null}
        <Button size="sm" variant="outline" disabled={busy} onClick={() => { void connect(profile.id); }}>{t('connections.connect')}</Button>
      </div>)}
      {!profiles && !error ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p> : null}
    </div>
    {profiles?.supports_remote ? <section className="space-y-3 border-t border-border pt-5">
      <h2 className="text-sm font-semibold">{t('connections.addRemote')}</h2>
      <RemoteConnectionForm draft={draft} onChange={setDraft} onSubmit={pair} busy={busy} />
    </section> : null}
    {error ? <div role="alert" className="space-y-2 text-sm text-destructive"><p className="break-words">{error}</p>{!profiles ? <Button variant="outline" onClick={retry}>{t('common.retry')}</Button> : null}</div> : null}
  </div>;
}
