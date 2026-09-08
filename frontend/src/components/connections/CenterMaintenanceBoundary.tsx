import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import type { FullDataClearInteractionGate } from '@/hooks/useFullDataClearInteractionGate';

/** Memory replacement blocks interaction while retaining mounted device drafts. */
export function CenterMaintenanceBoundary({ gate, onRetry, children }: {
  gate: FullDataClearInteractionGate;
  onRetry: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation('app');
  const blocked = gate.status !== 'idle';
  const failed = gate.status === 'failed';
  return <>
    <div hidden={blocked}>{blocked && gate.kind === 'clear' ? null : children}</div>
    <Dialog open={blocked}>
      <DialogContent hideClose className="z-[10000] max-w-xl p-6" overlayClassName="z-[9999] bg-background/95"
        onEscapeKeyDown={(event) => event.preventDefault()} onPointerDownOutside={(event) => event.preventDefault()}>
        <DialogTitle>{t(failed ? 'bootstrap.maintenanceRecoveryFailed' : 'bootstrap.maintenanceInProgress')}</DialogTitle>
        <DialogDescription className="mt-3">{t(failed ? 'bootstrap.maintenanceRecoveryHint' : 'bootstrap.maintenanceInProgressHint')}</DialogDescription>
        {failed ? <>
          <pre className="mt-5 whitespace-pre-wrap break-words rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">{gate.message}</pre>
          <Button className="mt-5" onClick={onRetry}><RotateCw className="h-4 w-4" />{t('bootstrap.retry')}</Button>
        </> : <div className="mt-5 h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />}
      </DialogContent>
    </Dialog>
  </>;
}
