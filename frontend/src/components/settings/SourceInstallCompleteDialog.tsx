import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';

export interface InstalledSourceTarget {
  pluginId: string;
  name: string;
}

export function SourceInstallCompleteDialog({ sources, onConfigure, onClose }: {
  sources: InstalledSourceTarget[];
  onConfigure: (pluginId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation('app');
  if (!sources.length) return null;
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent data-testid="source-install-complete-dialog">
      <DialogHeader>
        <DialogTitle>{t('settings.marketplace.sourceSetup.title')}</DialogTitle>
        <DialogDescription>{t('settings.marketplace.sourceSetup.description')}</DialogDescription>
      </DialogHeader>
      <ul className="space-y-3">
        {sources.map((source) => <li key={source.pluginId} className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium">{source.name}</span>
          {sources.length > 1 ? <Button onClick={() => onConfigure(source.pluginId)}>
            {t('settings.marketplace.sourceSetup.configure')}
          </Button> : null}
        </li>)}
      </ul>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>{t('settings.marketplace.sourceSetup.later')}</Button>
        {sources.length === 1 ? <Button onClick={() => onConfigure(sources[0].pluginId)}>
          {t('settings.marketplace.sourceSetup.configure')}
        </Button> : null}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
