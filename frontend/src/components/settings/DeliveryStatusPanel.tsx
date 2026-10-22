import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { channelEndpointsApi, type DeliveryStatus } from '@/api/modules/channelEndpoints';
import { Button } from '@/components/ui/button';

export function DeliveryStatusPanel() {
  const { t, i18n } = useTranslation('app');
  const [deliveries, setDeliveries] = useState<DeliveryStatus[]>([]);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(false);
    const load = async () => {
      try {
        const items = await channelEndpointsApi.status(controller.signal);
        if (!controller.signal.aborted) setDeliveries(items);
      } catch { if (!controller.signal.aborted) setError(true); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    return () => controller.abort();
  }, [revision]);

  return <section className="space-y-3 border-b py-6">
    <div className="flex items-center justify-between">
      <h3 className="text-sm font-semibold">{t('settings.deliveryStatus.title')}</h3>
      <Button size="sm" variant="outline" disabled={loading} onClick={() => setRevision(value => value + 1)}>
        {t('settings.deliveryStatus.refresh')}
      </Button>
    </div>
    <p className="text-sm text-muted-foreground">{t('settings.deliveryStatus.description')}</p>
    {error && <p role="alert" className="text-sm text-destructive">{t('settings.deliveryTargets.error')}</p>}
    {loading && <p role="status">{t('settings.deliveryTargets.loading')}</p>}
    {!loading && !error && deliveries.length === 0 && <p className="text-sm text-muted-foreground">{t('settings.deliveryStatus.empty')}</p>}
    {deliveries.length > 0 && <div className="max-h-72 overflow-auto"><table className="w-full text-left text-sm">
      <thead><tr><th>{t('settings.deliveryStatus.destination')}</th><th>{t('settings.deliveryStatus.status')}</th><th>{t('settings.deliveryStatus.updated')}</th></tr></thead>
      <tbody>{deliveries.map(item => <tr key={item.delivery_id} className="border-t">
        <td className="py-2">{[item.endpoint.connection_id, item.endpoint.target_id, item.endpoint.thread_id].filter(Boolean).join(' / ')}</td>
        <td className="px-3">{t(item.playback_state
          ? `settings.deliveryStatus.playback.${item.playback_state}`
          : `settings.deliveryStatus.states.${item.state}`)}</td>
        <td>{new Date(item.updated_at_ms).toLocaleString(i18n.resolvedLanguage)}</td>
      </tr>)}</tbody>
    </table></div>}
    {deliveries.some(item => item.state === 'uncertain') && <p className="text-sm text-amber-600">{t('settings.deliveryStatus.uncertainHint')}</p>}
  </section>;
}
