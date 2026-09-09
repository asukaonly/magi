import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { RemoteConnectionDraft } from './useConnectionSetup';

interface RemoteConnectionFormProps {
  id?: string;
  draft: RemoteConnectionDraft;
  onChange: (draft: RemoteConnectionDraft) => void;
  onSubmit: () => Promise<void>;
  busy: boolean;
  showSubmit?: boolean;
}

export function isRemoteConnectionDraftComplete(draft: RemoteConnectionDraft): boolean {
  return [draft.address, draft.token, draft.name, draft.deviceName].every((value) => value.trim().length > 0);
}

export function RemoteConnectionForm({ id, draft, onChange, onSubmit, busy, showSubmit = true }: RemoteConnectionFormProps) {
  const { t } = useTranslation('app');
  return <form id={id} className="space-y-5" onSubmit={(event) => {
    event.preventDefault();
    if (!busy && isRemoteConnectionDraftComplete(draft)) void onSubmit();
  }}>
    <p className="text-sm leading-6 text-muted-foreground">{t('connections.pairingHint')}</p>
    <label className="block space-y-2 text-sm"><span>{t('connections.address')}</span><Input type="url" placeholder="https://magi.example.com" value={draft.address} onChange={(event) => onChange({ ...draft, address: event.target.value })} required disabled={busy} autoComplete="off" spellCheck={false} /></label>
    <label className="block space-y-2 text-sm"><span>{t('connections.pairingCode')}</span><Input type="password" value={draft.token} onChange={(event) => onChange({ ...draft, token: event.target.value })} required disabled={busy} autoComplete="off" /></label>
    <div className="grid gap-5 sm:grid-cols-2">
      <label className="block space-y-2 text-sm"><span>{t('connections.name')}</span><Input value={draft.name} onChange={(event) => onChange({ ...draft, name: event.target.value })} maxLength={64} required disabled={busy} autoComplete="off" /></label>
      <label className="block space-y-2 text-sm"><span>{t('connections.deviceName')}</span><Input value={draft.deviceName} onChange={(event) => onChange({ ...draft, deviceName: event.target.value })} maxLength={64} required disabled={busy} autoComplete="off" /></label>
    </div>
    <p className="text-xs leading-5 text-muted-foreground">{t('connections.ownerAccess')}</p>
    {showSubmit ? <Button type="submit" disabled={busy || !isRemoteConnectionDraftComplete(draft)}>{t(busy ? 'connections.connecting' : 'connections.pair')}</Button> : null}
  </form>;
}
