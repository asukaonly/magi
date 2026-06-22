import { useCallback, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
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

export interface ProductTourProps {
  /** Called when the first-run setup prompt is completed or skipped. */
  onComplete: () => void;
}

export function ProductTour({ onComplete }: ProductTourProps): JSX.Element {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(true);
  const doneRef = useRef(false);

  const finish = useCallback(() => {
    if (doneRef.current) {
      return;
    }
    doneRef.current = true;
    setOpen(false);
    onComplete();
  }, [onComplete]);

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
            showBrowseAll={false}
            fallbackPluginIds={['chrome-history', 'git-activity']}
            onConnectStart={finish}
          />
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            {t('productTour.firstContextNote')}
          </p>
        </div>

        <DialogFooter className="justify-between bg-background/95 px-7">
          <Button variant="ghost" onClick={finish}>
            {t('productTour.skip')}
          </Button>
          <Button onClick={finish} className="gap-2">
            {t('productTour.enterChat')}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ProductTour;
