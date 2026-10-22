import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { channelEndpointsApi, endpointKey, type EndpointRef, type EndpointView } from '@/api/modules/channelEndpoints';
import { Button } from '@/components/ui/button';
import { DeliveryStatusPanel } from './DeliveryStatusPanel';

export function DeliveryTargetsPanel() {
  const { t } = useTranslation('app');
  const [endpoints, setEndpoints] = useState<EndpointView[]>([]);
  const [selected, setSelected] = useState<EndpointRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const [catalog, targets] = await Promise.all([
          channelEndpointsApi.list(controller.signal), channelEndpointsApi.preferences(controller.signal),
        ]);
        if (!controller.signal.aborted) { setEndpoints(catalog); setSelected(targets); }
      } catch { if (!controller.signal.aborted) setError(true); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load();
    return () => controller.abort();
  }, []);

  const save = async () => {
    setSaving(true); setError(false); setSaved(false);
    try { setSelected(await channelEndpointsApi.save(selected)); setSaved(true); }
    catch { setError(true); }
    finally { setSaving(false); }
  };
  const known = new Set(endpoints.map(item => endpointKey(item.endpoint)));
  const missing = selected.filter(item => !known.has(endpointKey(item)));
  const toggle = (endpoint: EndpointRef, enabled: boolean) => {
    setSaved(false);
    setSelected(current => enabled ? [...current, endpoint] : current.filter(item => endpointKey(item) !== endpointKey(endpoint)));
  };

  return <><section className="space-y-3 border-b pb-6">
    <h3 className="text-sm font-semibold">{t('settings.deliveryTargets.title')}</h3>
    <p className="text-sm text-muted-foreground">{t('settings.deliveryTargets.description')}</p>
    {loading ? <p role="status">{t('settings.deliveryTargets.loading')}</p> : <>
      {endpoints.length === 0 && <p className="text-sm text-muted-foreground">{t('settings.deliveryTargets.empty')}</p>}
      {endpoints.map(item => <label key={endpointKey(item.endpoint)} className="flex items-center gap-3 text-sm">
        <input type="checkbox" checked={selected.some(value => endpointKey(value) === endpointKey(item.endpoint))}
          disabled={saving || !item.capabilities.includes('message')}
          onChange={event => toggle(item.endpoint, event.currentTarget.checked)} />
        <span>{item.label}<span className="ml-2 text-xs text-muted-foreground">
          {[item.endpoint.connection_id, item.endpoint.thread_id].filter(Boolean).join(' / ')}
          {' · '}{t(item.available ? 'settings.deliveryTargets.available' : 'settings.deliveryTargets.unavailable')}
          {item.capabilities.includes('audio') && ` · ${t('settings.deliveryTargets.audio')}`}
        </span></span>
      </label>)}
      {missing.map(endpoint => <label key={endpointKey(endpoint)} className="flex items-center gap-3 text-sm">
        <input type="checkbox" checked disabled={saving} onChange={() => toggle(endpoint, false)} />
        <span>{endpoint.target_id} · {t('settings.deliveryTargets.removed')}</span>
      </label>)}
      <Button size="sm" disabled={saving || selected.length > 32} onClick={() => { void save(); }}>
        {t(saving ? 'settings.deliveryTargets.saving' : 'settings.deliveryTargets.save')}
      </Button>
    </>}
    {error && <p role="alert" className="text-sm text-destructive">{t('settings.deliveryTargets.error')}</p>}
    {saved && <p role="status" className="text-sm">{t('settings.deliveryTargets.saved')}</p>}
  </section><DeliveryStatusPanel /></>;
}
