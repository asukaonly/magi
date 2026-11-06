import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { requestClientReset } from '@/runtime/client-reset';

export function ClientResetAction() {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  return <>
    <Button variant="outline" onClick={() => { setConfirmed(false); setOpen(true); }}>{t('clientReset.title')}</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] flex-col sm:max-w-lg">
        <DialogHeader className="shrink-0 pr-14">
          <DialogTitle>{t('clientReset.confirmTitle')}</DialogTitle>
          <DialogDescription>{t('clientReset.description')}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 space-y-4 overflow-y-auto px-6 pb-6">
          <ul className="list-disc space-y-2 pl-5 text-sm leading-6">
            <li>{t('clientReset.connections')}</li>
            <li>{t('clientReset.content')}</li>
            <li>{t('clientReset.service')}</li>
          </ul>
          <p className="rounded-md bg-muted p-3 text-sm leading-6">{t('clientReset.preserved')}</p>
          <label className="flex items-start gap-3 text-sm leading-6">
            <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-primary" checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)} />
            <span>{t('clientReset.acknowledge')}</span>
          </label>
        </div>
        <DialogFooter className="shrink-0">
          <Button variant="outline" onClick={() => setOpen(false)}>{t('clientReset.cancel')}</Button>
          <Button variant="destructive" disabled={!confirmed} onClick={requestClientReset}>{t('clientReset.confirm')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
