import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { serverApi, type CenterNotificationMode } from '@/api/modules/server';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { Button } from '@/components/ui/button';

export function CenterNotificationPolicy() {
  const { t } = useTranslation('app');
  const [mode, setMode] = useState<CenterNotificationMode | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owner = useRef(0);
  const busy = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const load = useCallback(async () => {
    if (busy.current) return;
    const generation = ++owner.current;
    try {
      const result = await serverApi.notificationPolicy();
      if (generation === owner.current) { setMode(result.mode); setError(null); }
    } catch {
      if (generation === owner.current) setError(t('connections.notifications.loadFailed'));
    }
  }, [t]);
  useEffect(() => { void load(); return () => { owner.current += 1; }; }, [load]);
  useCenterRefresh(load, !pending);
  const update = async (next: string) => {
    if (busy.current || (next !== 'single_device' && next !== 'all_devices')) return;
    busy.current = true; setPending(true); setError(null);
    const generation = ++owner.current;
    try {
      const result = await serverApi.setNotificationPolicy(next);
      if (generation === owner.current) setMode(result.mode);
    } catch {
      if (generation === owner.current) setError(t('connections.notifications.saveFailed'));
    } finally {
      busy.current = false;
      if (mounted.current) setPending(false);
    }
  };
  return <div className="space-y-2 border-b border-border pb-5">
    <label htmlFor="center-notification-mode" className="text-sm font-semibold">{t('connections.notifications.title')}</label>
    <p className="text-xs text-muted-foreground">{t('connections.notifications.description')}</p>
    {mode ? <select id="center-notification-mode" className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm" value={mode} disabled={pending} onChange={(event) => { void update(event.target.value); }}>
      <option value="single_device">{t('connections.notifications.single')}</option>
      <option value="all_devices">{t('connections.notifications.all')}</option>
    </select> : null}
    <p className="text-xs leading-5 text-muted-foreground">{t('connections.notifications.hint')}</p>
    {error ? <div role="alert" className="text-xs text-destructive">{error}<Button variant="ghost" size="sm" disabled={pending} onClick={() => { void load(); }}>{t('common.retry')}</Button></div> : null}
  </div>;
}
