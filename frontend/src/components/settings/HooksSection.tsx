import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { hooksApi, type HookEntry } from '@/api';
import {
  SettingsGroup,
  SettingsSectionShell,
} from '@/components/settings/SettingsSectionPrimitives';

export function HooksSection() {
  const { t } = useTranslation('app');
  const [entries, setEntries] = useState<HookEntry[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await hooksApi.list();
        if (!cancelled) {
          setEntries(data.entries);
          setTotal(data.total);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = entries.reduce<Record<string, HookEntry[]>>((acc, entry) => {
    (acc[entry.event_type] ??= []).push(entry);
    return acc;
  }, {});
  const groupKeys = Object.keys(grouped).sort();

  return (
    <SettingsSectionShell>
      <SettingsGroup
        title={t('settings.hooks.title')}
        description={t('settings.hooks.description')}
      >
        {loading && (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        )}
        {error && !loading && (
          <p className="text-sm text-destructive">
            {t('settings.hooks.loadError', { error })}
          </p>
        )}
        {!loading && !error && total === 0 && (
          <p className="text-sm text-muted-foreground">
            {t('settings.hooks.empty')}
          </p>
        )}
        {!loading && !error && total > 0 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {t('settings.hooks.totalCount', { count: total })}
            </p>
            {groupKeys.map((event) => (
              <div
                key={event}
                className="rounded-lg border border-border/60 bg-background/50 p-3"
              >
                <div className="mb-2 flex items-center gap-2">
                  <span className="font-medium text-foreground">{event}</span>
                  <span className="text-xs text-muted-foreground">
                    {t('settings.hooks.handlerCount', { count: grouped[event].length })}
                  </span>
                </div>
                <ul className="space-y-1">
                  {grouped[event].map((entry, idx) => (
                    <li
                      key={`${event}-${idx}`}
                      className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
                    >
                      <span className="font-mono text-foreground">
                        {entry.source ?? t('settings.hooks.sourceUnknown')}
                      </span>
                      {entry.matcher && (
                        <span className="rounded-full border border-border/60 px-2 py-0.5">
                          {t('settings.hooks.matcherPrefix')}: {entry.matcher}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </SettingsGroup>
    </SettingsSectionShell>
  );
}

export default HooksSection;
