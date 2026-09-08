import { CenterAccessPanel } from './CenterAccessPanel';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Server } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ConnectionPicker } from './ConnectionPicker';

export function ConnectionsButton() {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary" title={t('connections.title')} aria-label={t('connections.title')} onClick={() => setOpen(true)}><Server className="h-[18px] w-[18px]" /></button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle>{t('connections.title')}</DialogTitle><DialogDescription>{t('connections.switchHint')}</DialogDescription></DialogHeader>
        <div className="space-y-6 px-6 pb-6"><ConnectionPicker /><CenterAccessPanel /></div>
      </DialogContent>
    </Dialog>
  </>;
}
