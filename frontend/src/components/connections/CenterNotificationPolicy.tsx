import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { serverApi, type CenterNotificationMode } from '@/api/modules/server';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { Button } from '@/components/ui/button';
import { LabeledSelectField } from '@/components/settings/form-fields';
import { SettingsGroup } from '@/components/settings/SettingsSectionPrimitives';

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
  useCenterRefresh(load, ["server"], !pending);
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
  return <SettingsGroup title={t('connections.notifications.title')} description={t('connections.notifications.description')}>
    {mode ? <LabeledSelectField label="" ariaLabel={t('connections.notifications.title')} value={mode} disabled={pending}
      className="sm:max-w-sm" onChange={(value) => { void update(value); }}
      options={[
        { value: 'single_device', label: t('connections.notifications.single') },
        { value: 'all_devices', label: t('connections.notifications.all') },
      ]} /> : !error ? <p role="status" className="text-sm text-muted-foreground">{t('common.loading')}</p> : null}
    <p className="text-xs leading-5 text-muted-foreground">{t(mode === 'all_devices' ? 'connections.notifications.allHint' : 'connections.notifications.hint')}</p>
    <p className="text-xs text-muted-foreground">{t('connections.notifications.autoSaved')}</p>
    {error ? <div role="alert" className="text-xs text-destructive">{error}<Button variant="ghost" size="sm" disabled={pending} onClick={() => { void load(); }}>{t('common.retry')}</Button></div> : null}
  </SettingsGroup>;
}
