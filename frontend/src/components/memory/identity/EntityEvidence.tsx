import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type L1Event } from '@/api/modules/memory';
import { useRequestOwner } from '@/hooks/useRequestOwner';

export function EntityEvidence({ eventIds }: { eventIds: string[] }) {
  const { t } = useTranslation('app');
  const scope = JSON.stringify(eventIds.slice(0, 3));
  const ownRequest = useRequestOwner(scope);
  const [records, setRecords] = useState<L1Event[]>([]);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const isCurrent = ownRequest('evidence');
    setLoading(true);
    setRecords([]);
    setUnavailable(false);
    const ids: unknown = JSON.parse(scope);
    if (!Array.isArray(ids)) return;
    const keys = ids.filter((id): id is string => typeof id === 'string');
    void Promise.allSettled(keys.map((eventId) => memoryApi.getL1Events({ event_id: eventId, limit: 1 }))).then((results) => {
      if (!isCurrent()) return;
      setRecords(results.flatMap((result) => result.status === 'fulfilled' ? result.value.items : []));
      setUnavailable(results.some((result) => result.status === 'rejected'));
      setLoading(false);
    });
    return () => { ownRequest('evidence'); };
  }, [scope, ownRequest]);
  return <div className="space-y-2 text-sm text-muted-foreground">
    {loading ? <p>{t('memory.identity.loading')}</p> : records.map((record) => <blockquote key={record.event_id} className="whitespace-pre-wrap break-words border-l-2 pl-3"><p>{record.content}</p><span className="text-xs">{new Date(record.timestamp * 1000).toLocaleString()}</span></blockquote>)}
    {!loading && (unavailable || records.length === 0) ? <p>{t('memory.identity.evidenceUnavailable')}</p> : null}
  </div>;
}
