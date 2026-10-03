import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { sourcesApi, type SourceSyncHistory as SyncHistory } from '@/api/modules/sources';
import { Button } from '@/components/ui/button';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { getErrorMessage } from '@/utils/error-handler';

export function SourceSyncHistory({ sourceName, connectionId, refreshKey }: {
  sourceName: string; connectionId: string; refreshKey: string;
}) {
  const { t, i18n } = useTranslation('app');
  const [history, setHistory] = useState<SyncHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const begin = useRequestOwner(JSON.stringify([sourceName, connectionId]));
  const load = useCallback(async (offset = 0) => {
    const current = begin('history');
    setLoading(true);
    try {
      const next = await sourcesApi.getSyncHistory(sourceName, connectionId, offset);
      if (!current()) return;
      setHistory(previous => ({ ...next, items: offset && previous ? [...previous.items, ...next.items] : next.items }));
      setError(null);
    } catch (err) {
      if (current()) setError(getErrorMessage(err) || String(err));
    } finally {
      if (current()) setLoading(false);
    }
  }, [begin, sourceName, connectionId]);
  useEffect(() => { void load(); }, [load, refreshKey]);
  useCenterRefresh(() => load(), ['sources']);
  const formatTime = (time: number | null) => time ? new Intl.DateTimeFormat(i18n.language, {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(time * 1000)) : '—';
  return (
    <section className="rounded-2xl bg-[hsl(var(--memory-panel-elevated)/0.64)] p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{t('sourceRecovery.historyTitle')}</h2>
        <Button size="sm" variant="ghost" disabled={loading} onClick={() => void load()}>{t('sourceRecovery.refresh')}</Button>
      </div>
      {error ? <div role="alert" className="mb-3 text-sm text-destructive">{t('sourceRecovery.historyFailed', { message: error })}</div> : null}
      {history?.items.length ? <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs font-normal text-muted-foreground"><tr>
            <th className="pb-3 pr-4 font-normal">{t('sourceRecovery.time')}</th>
            <th className="pb-3 pr-4 font-normal">{t('sourceRecovery.result')}</th>
            <th className="pb-3 font-normal">{t('sourceRecovery.reason')}</th>
          </tr></thead>
          <tbody>{history.items.map(item => <tr key={item.job_id} className="align-top">
            <td className="whitespace-nowrap py-3 pr-4 text-muted-foreground">{formatTime(item.finished_at ?? item.started_at ?? item.created_at)}</td>
            <td className="whitespace-nowrap py-3 pr-4">
              {t(`sourceRecovery.status.${['success', 'failed', 'queued', 'running', 'retrying', 'continuing'].includes(item.status) ? item.status : 'unknown'}`)}
              {item.attempt_count > 1 ? <span className="mt-1 block text-xs text-muted-foreground">{t('sourceRecovery.attempts', { count: item.attempt_count })}</span> : null}
            </td>
            <td className="min-w-48 py-3">
              {item.error ? <details>
                <summary className="cursor-pointer text-muted-foreground">{t(item.failure?.code === 'file_access_denied' || item.failure?.code === 'permission_required' ? 'sourceRecovery.permissionTitle' : 'sourceRecovery.details')}</summary>
                <p className="mt-2 max-w-2xl whitespace-pre-wrap wrap-break-word text-xs leading-5 text-muted-foreground wrap-anywhere">{item.error}</p>
              </details> : <span className="text-muted-foreground">—</span>}
            </td>
          </tr>)}</tbody>
        </table>
      </div> : !error ? <p className="text-sm text-muted-foreground">{t(loading ? 'sourceRecovery.loading' : 'sourceRecovery.historyEmpty')}</p> : null}
      {history && history.items.length < history.total ? <Button variant="ghost" size="sm" disabled={loading} onClick={() => void load(history.items.length)}>{t('sourceRecovery.loadMore')}</Button> : null}
    </section>
  );
}
