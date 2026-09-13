import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { api, unwrapGatewayPayload } from '@/api/client';
import { Button } from '@/components/ui/button';
import { getRuntimeGeneration } from '@/runtime/config';
import { readBackgroundDeliveryStatus, retryBackgroundDelivery, type BackgroundDeliveryStatus } from '@/runtime/background-delivery';

const inboxSchema = z.object({ pending: z.number().int().nonnegative(), failed: z.number().int().nonnegative() });
type Inbox = z.infer<typeof inboxSchema>;

export function BackgroundDeliveryPanel() {
  const { t } = useTranslation('app');
  const [local, setLocal] = useState<BackgroundDeliveryStatus | null>(null);
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
  return <section className="space-y-3 border-t border-border pt-5">
    <h2 className="text-sm font-semibold">{t('connections.delivery.title')}</h2>
    <p className="text-xs leading-5 text-muted-foreground">{t('connections.delivery.description')}</p>
    {local ? <p className="text-sm" role="status">{t('connections.delivery.outbox', { pending: local.queue.pending, failed: local.queue.failed })}</p> : null}
    <p className="text-sm text-muted-foreground">{inbox ? t('connections.delivery.inbox', inbox) : t(serverLoaded ? 'connections.delivery.serverUnavailable' : 'common.loading')}</p>
    {(local?.queue.failed ?? 0) + (inbox?.failed ?? 0) > 0 ? <Button variant="outline" size="sm" disabled={busy} onClick={() => { void retry(); }}>{t('connections.delivery.retry')}</Button> : null}
    {error ? <p role="alert" className="text-xs text-destructive">{t('connections.delivery.failed')}</p> : null}
  </section>;
}
