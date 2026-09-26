import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import type { PluginCapability } from '@/api/modules/plugins';
import { PluginIcon } from './PluginIcon';
import { PluginCapabilityList } from './PluginCapabilityList';

export type ConsentMode = 'install' | 'update' | 'sideload' | 'trust';

interface Props {
  open: boolean;
  mode: ConsentMode;
  pluginName: string;
  pluginIcon?: string | null;
  version: string;
  official?: boolean;
  executionMode?: 'restricted_process' | 'trusted_process';
  capabilities: PluginCapability[];
  newCapabilities?: PluginCapability[];
  confirmDisabled?: boolean;
  statusMessage?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export const PluginConsentDialog: React.FC<Props> = ({
  open, mode, pluginName, pluginIcon, version, official, executionMode, capabilities,
  newCapabilities, confirmDisabled = false, statusMessage, onConfirm, onCancel,
}) => {
  const { t } = useTranslation('app');
  const isUpdate = mode === 'update' && (newCapabilities?.length ?? 0) > 0;
  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onCancel(); }}>
      <DialogContent className="flex max-h-[90dvh] max-w-lg flex-col">
        <DialogHeader className="pr-12">
          <div className="flex min-w-0 items-start gap-3">
            <PluginIcon iconId={pluginIcon || 'lucide:package'} className="mt-0.5 h-9 w-9 shrink-0" />
            <div className="min-w-0 space-y-1.5">
              <DialogTitle className="break-words leading-7">
                {t(mode === 'trust' ? 'plugins.trust.title' : `settings.marketplace.consent.title.${mode}`, { name: pluginName })}
              </DialogTitle>
              <DialogDescription>{t(mode === 'trust' ? 'settings.marketplace.consent.trustDescription' : 'settings.marketplace.consent.installDescription')}</DialogDescription>
              {!official ? <p className="text-xs text-muted-foreground">{t('settings.marketplace.consent.thirdParty')}</p> : null}
            </div>
          </div>
        </DialogHeader>
        <div className="min-h-0 space-y-5 overflow-y-auto px-6 pb-5">
          {mode === 'sideload' ? <p role="note" className="text-sm leading-relaxed text-muted-foreground">{t('settings.marketplace.consent.sideloadWarning')}</p> : null}
          {isUpdate ? <div className="space-y-3">
            <p className="text-sm font-medium">{t('settings.marketplace.consent.updateNewLede')}</p>
            <PluginCapabilityList capabilities={newCapabilities ?? []} highlight />
          </div> : null}
          {statusMessage ? <p role="status" className="text-sm text-muted-foreground">{statusMessage}</p>
            : <PluginCapabilityList capabilities={capabilities} />}
          {executionMode === 'trusted_process' ? <div className="space-y-1.5 border-t pt-4 text-sm">
            <p className="font-medium">{t('settings.marketplace.plan.executionAccess')}</p>
            <p className="leading-relaxed text-muted-foreground">{t('plugins.trust.nativeAccess')}</p>
          </div> : null}
          <details className="group border-t pt-3">
            <summary className="flex cursor-pointer list-none items-center justify-between rounded-sm py-1 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
              {t('settings.marketplace.consent.details')}
              <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <div className="space-y-3 pt-4">
              <p className="text-sm">v{version}</p>
              {executionMode ? <p className="text-xs text-muted-foreground">{t(executionMode === 'trusted_process' ? 'settings.marketplace.plan.trustedMode' : 'settings.marketplace.plan.restrictedMode')}</p> : null}
              <PluginCapabilityList capabilities={capabilities} detailed />
            </div>
          </details>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>{t('settings.marketplace.consent.cancel')}</Button>
          <Button onClick={onConfirm} disabled={confirmDisabled}>
            {t(mode === 'trust' ? 'plugins.trust.confirm' : mode === 'update' ? 'settings.marketplace.consent.confirm.update' : 'settings.marketplace.consent.confirm.install')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PluginConsentDialog;
