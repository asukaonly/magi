import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { subscribeRuntimeReset } from '@/runtime/config';
import { usePluginRequestRecoveryStore, type PluginRequestRecovery } from '@/stores/plugin-request-recovery';

function ReviewAttempt({ request }: { request: PluginRequestRecovery }) {
  const { t } = useTranslation('app');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const close = async () => {
    if (!acknowledged || busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const result = await request.resolve();
      const state = usePluginRequestRecoveryStore.getState();
      if (state.request?.operationId !== request.operationId) return;
      state.finish(request, result);
      toast.info(t(`plugins.requestRecovery.${result}`));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) usePluginRequestRecoveryStore.getState().dismiss(); }}>
      <DialogContent className="space-y-5 p-6" hideClose={busy}>
        <DialogHeader>
          <DialogTitle>{t('plugins.requestRecovery.title')}</DialogTitle>
          <DialogDescription>{t('plugins.requestRecovery.description')}</DialogDescription>
        </DialogHeader>
        <label className="flex items-start gap-3 text-sm">
          <input type="checkbox" checked={acknowledged} disabled={busy} onChange={(event) => setAcknowledged(event.target.checked)} />
          <span>{t('plugins.requestRecovery.acknowledged')}</span>
        </label>
        {failed ? <p role="alert" className="text-sm text-destructive">{t('plugins.requestRecovery.failed')}</p> : null}
        <DialogFooter>
          <Button variant="ghost" disabled={busy} onClick={() => usePluginRequestRecoveryStore.getState().dismiss()}>{t('plugins.requestRecovery.later')}</Button>
          <Button disabled={!acknowledged || busy} onClick={() => { void close(); }}>{t('plugins.requestRecovery.close')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function PluginRequestRecoveryDialog() {
  const request = usePluginRequestRecoveryStore((state) => state.request);
  useEffect(() => subscribeRuntimeReset(() => usePluginRequestRecoveryStore.getState().reset()), []);
  return request ? <ReviewAttempt key={request.operationId} request={request} /> : null;
}
