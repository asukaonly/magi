import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { entityIdentityApi, type IdentityEntity, type IdentityWire } from '@/api/modules/entityIdentity';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { canChangeEntityIdentity, getEntityTypeLabel } from '@/utils/entity-types';
import { asEventHandler } from '@/utils/as-event-handler';
import { Button } from '@/components/ui/button';

export function EntityIdentityAudit({ onSelect }: { onSelect: (entity: IdentityEntity) => void }) {
  const { t } = useTranslation('app');
  const [data, setData] = useState<IdentityWire<'EntityIdentityAudit'> | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const ownRequest = useRequestOwner();
  const load = async (nextOffset: number) => {
    const isCurrent = ownRequest('audit');
    setBusy(true);
    try {
      const result = await entityIdentityApi.audit(nextOffset);
      if (isCurrent()) { setData(result); setOffset(nextOffset); setError(false); }
    } catch { if (isCurrent()) setError(true); }
    finally { if (isCurrent()) setBusy(false); }
  };
  return <section className="space-y-3 rounded-xl border p-4">
    <div className="flex items-center justify-between gap-4"><div><h2 className="font-medium">{t('memory.identity.auditTitle')}</h2><p className="text-sm text-muted-foreground">{t('memory.identity.auditHelp')}</p></div><Button variant="outline" disabled={busy} onClick={asEventHandler(() => load(0))}>{t('memory.identity.auditLoad')}</Button></div>
    {error ? <p role="alert">{t('memory.identity.searchFailed')}</p> : null}
    {data?.groups.map((group) => <div key={group.name} className="space-y-2 border-t pt-3"><p className="font-medium">{group.name}</p><div className="flex flex-wrap gap-2">{group.entities.map((entity, index) => <Button key={entity.entity_id} variant="outline" disabled={!canChangeEntityIdentity(entity)} onClick={() => onSelect(entity)}>{t('memory.identity.auditEntry', { name: entity.canonical_name, type: getEntityTypeLabel(entity.entity_type, t), index: index + 1 })}</Button>)}</div></div>)}
    {data?.total === 0 ? <p>{t('memory.identity.auditEmpty')}</p> : null}
    {data && data.total > 25 ? <div className="flex gap-2"><Button variant="outline" disabled={busy || offset === 0} onClick={asEventHandler(() => load(Math.max(0, offset - 25)))}>{t('memory.identity.previous')}</Button><Button variant="outline" disabled={busy || offset + data.groups.length >= data.total} onClick={asEventHandler(() => load(offset + 25))}>{t('memory.identity.next')}</Button></div> : null}
  </section>;
}
