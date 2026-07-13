import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { EmptyStateAvailableSensors } from '@/components/empty-state/EmptyStateAvailableSensors';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

export interface ProductTourProps {
  /** Called when the first-run setup prompt is completed or skipped. */
  onComplete: () => void;
}

export function ProductTour({ onComplete }: ProductTourProps): JSX.Element {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(true);
  const pluginPanelOpen = usePluginInstallPanelStore((s) => s.open);
  const doneRef = useRef(false);
  const awaitingPluginRef = useRef(false);

  const finish = useCallback(() => {
    if (doneRef.current) {
      return;
    }
    doneRef.current = true;
    awaitingPluginRef.current = false;
    setOpen(false);
    onComplete();
  }, [onComplete]);

  useEffect(() => {
    if (!pluginPanelOpen && awaitingPluginRef.current && !doneRef.current) {
      awaitingPluginRef.current = false;
      setOpen(true);
    }
  }, [pluginPanelOpen]);

  const preventDismiss = (event: Event) => {
    event.preventDefault();
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className="max-w-[44rem] overflow-hidden p-0"
        hideClose
        onEscapeKeyDown={preventDismiss}
        onInteractOutside={preventDismiss}
        onPointerDownOutside={preventDismiss}
      >
        <DialogHeader className="border-b border-border/55 bg-muted/25 px-7 py-6">
          <div className="mb-3 w-fit rounded-full border border-primary/20 bg-background px-3 py-1 text-xs font-medium text-primary">
            {t('productTour.firstContextKicker')}
          </div>
          <DialogTitle className="max-w-xl text-xl font-semibold leading-7">
            {t('productTour.firstContextTitle')}
          </DialogTitle>
          <DialogDescription className="max-w-xl text-sm leading-6">
            {t('productTour.firstContextBody')}
          </DialogDescription>
        </DialogHeader>

        <div className="px-7 py-5">
          <EmptyStateAvailableSensors
            variant="first_context"
            showBrowseAll={false}
            panelContext="first_context"
            onConnectStart={() => {
              awaitingPluginRef.current = true;
              setOpen(false);
            }}
            onConnectDone={finish}
          />
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            {t('productTour.firstContextNote')}
          </p>
        </div>

        <DialogFooter className="justify-end border-border/55 bg-background px-7 py-4">
          <Button onClick={finish}>
            {t('productTour.connectLater')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ProductTour;
