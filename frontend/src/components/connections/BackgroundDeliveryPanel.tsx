import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { api, unwrapGatewayPayload } from '@/api/client';
import { Button } from '@/components/ui/button';
import { getRuntimeGeneration } from '@/runtime/config';
import { deliveryStreamSchema, readBackgroundStreams, recoverBackgroundStream, readBackgroundDeliveryStatus, retryBackgroundDelivery, type BackgroundDeliveryStatus } from '@/runtime/background-delivery';

const serverStreamSchema = deliveryStreamSchema.extend({ producer_id: z.string() });
const inboxSchema = z.object({ pending: z.number().int().nonnegative(), failed: z.number().int().nonnegative(), streams: z.array(serverStreamSchema), truncated: z.boolean() });
type Inbox = z.infer<typeof inboxSchema>;

export function BackgroundDeliveryPanel() {
  const { t } = useTranslation('app');
  const [local, setLocal] = useState<BackgroundDeliveryStatus | null>(null);
  const [streams, setStreams] = useState<z.infer<typeof deliveryStreamSchema>[]>([]);
  const [discarding, setDiscarding] = useState<string | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [serverLoaded, setServerLoaded] = useState(false);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const owner = useRef(0);
  const running = useRef(false);
  const mounted = useRef(false);
  const actionPending = useRef(false);
  const load = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    const request = ++owner.current;
    const generation = getRuntimeGeneration();
    const current = () => request === owner.current && generation === getRuntimeGeneration();
    try {
      await Promise.all([
        readBackgroundDeliveryStatus().then((outbox) => {
          if (current()) { setLocal(outbox); setError(false); }
        }).catch(() => { if (current()) setError(true); }),
        readBackgroundStreams().then((rows) => { if (current()) setStreams(rows); }).catch(() => { if (current()) setError(true); }),
        api.get<unknown>('/delivery/status').then((r) => inboxSchema.parse(unwrapGatewayPayload(r)))
          .then((server) => { if (current()) setInbox(server); })
          .catch(() => { if (current()) setInbox(null); })
          .finally(() => { if (current()) setServerLoaded(true); }),
      ]);
    } finally { running.current = false; }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void load();
    const timer = window.setInterval(() => { void load(); }, 5000);
    return () => { mounted.current = false; owner.current += 1; window.clearInterval(timer); };
  }, [load]);
  const retry = async () => {
    if (actionPending.current) return;
    actionPending.current = true;
    setBusy(true);
    const request = owner.current;
    const generation = getRuntimeGeneration();
    try {
      if (local?.queue.failed) await retryBackgroundDelivery();
      if (generation !== getRuntimeGeneration()) return;
      if (inbox?.failed) await api.post('/delivery/retry', {});
      if (request === owner.current) { setError(false); await load(); }
    } catch { if (request === owner.current) setError(true); }
    finally { actionPending.current = false; if (mounted.current) setBusy(false); }
  };
  const recover = async (row: z.infer<typeof deliveryStreamSchema> & { producer_id?: string }, discard: boolean) => {
    const key = `${row.producer_id ?? 'local'}:${row.connection_id}:${row.stream}`;
    if (discard && discarding !== key) { setDiscarding(key); return; }
    if (actionPending.current) return;
    actionPending.current = true;
    setBusy(true);
    const generation = getRuntimeGeneration();
    try {
      if (row.producer_id) await api.post(discard ? '/delivery/discard' : '/delivery/retry', {
        producer_id: row.producer_id, connection_id: row.connection_id, stream: row.stream,
      });
      else await recoverBackgroundStream(row.stream, discard);
      if (mounted.current && generation === getRuntimeGeneration()) { setDiscarding(null); await load(); }
    } catch { if (mounted.current && generation === getRuntimeGeneration()) setError(true); }
    finally { actionPending.current = false; if (mounted.current) setBusy(false); }
  };
  const rows = [...streams, ...(inbox?.streams ?? [])] as (z.infer<typeof deliveryStreamSchema> & { producer_id?: string })[];
  return <section className="space-y-3 border-t border-border pt-5">
    <h2 className="text-sm font-semibold">{t('connections.delivery.title')}</h2>
    <p className="text-xs leading-5 text-muted-foreground">{t('connections.delivery.description')}</p>
    {local ? <p className="text-sm" role="status">{t('connections.delivery.outbox', { pending: local.queue.pending, failed: local.queue.failed })}</p> : null}
    <p className="text-sm text-muted-foreground">{inbox ? t('connections.delivery.inbox', inbox) : t(serverLoaded ? 'connections.delivery.serverUnavailable' : 'common.loading')}</p>
    {(local?.queue.failed ?? 0) + (inbox?.failed ?? 0) > 0 ? <Button variant="outline" size="sm" disabled={busy} onClick={() => { void retry(); }}>{t('connections.delivery.retry')}</Button> : null}
    <div className="max-h-80 space-y-3 overflow-y-auto">{rows.map((row) => {
      const key = `${row.producer_id ?? 'local'}:${row.connection_id}:${row.stream}`;
      const knownCodes = ['permission_required', 'invalid_payload', 'unsupported_schema', 'temporarily_unavailable', 'handler_timeout', 'handler_failed', 'connection_unavailable', 'connection_epoch_changed', 'authorization_unavailable', 'connection_unavailable', 'receipt_capacity', 'inbox_full'];
      return <div key={key} className="space-y-2 rounded-md border border-border p-3 text-xs">
        <p className="break-all font-medium">{row.plugin_target ?? t('connections.delivery.notifications')} · {row.stream}</p>
        <p className="break-all text-muted-foreground">{row.producer_id ? t('connections.delivery.device', { id: row.producer_id }) : t('connections.delivery.thisDevice')}{row.connection_id ? ` · ${row.connection_id}` : ''}</p>
        <p>{t('connections.delivery.streamCounts', { pending: row.pending, failed: row.failed, attempts: row.attempts })}</p>
        <p>{t('connections.delivery.oldest', { time: new Date(row.oldest_at_ms).toLocaleString() })}</p>
        {row.last_error ? <p>{t(`connections.delivery.reasons.${knownCodes.includes(row.last_error) ? row.last_error : 'unknown'}`)}</p> : null}
        {row.next_retry_at_ms ? <p>{t('connections.delivery.nextRetry', { time: new Date(row.next_retry_at_ms).toLocaleString() })}</p> : null}
        <div className="flex gap-2">
          {row.failed > 0 ? <Button variant="outline" size="sm" disabled={busy} onClick={() => { void recover(row, false); }}>{t('connections.delivery.retryStream')}</Button> : null}
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => { void recover(row, true); }}>{t(discarding === key ? 'connections.delivery.confirmDiscard' : 'connections.delivery.discard')}</Button>
        </div>
      </div>;
    })}</div>
    {(streams.length >= 100 || inbox?.truncated) ? <p className="text-xs text-muted-foreground">{t('connections.delivery.truncated')}</p> : null}
    {error ? <p role="alert" className="text-xs text-destructive">{t('connections.delivery.failed')}</p> : null}
  </section>;
}
