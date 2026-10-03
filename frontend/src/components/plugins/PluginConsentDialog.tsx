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
import { PluginRuntimeAccessNotice } from './PluginRuntimeAccessNotice';

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
  const nativeAccess = executionMode === 'trusted_process';
  const showRuntimeNotice = nativeAccess && (!official || mode === 'sideload');
  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onCancel(); }}>
      <DialogContent className="flex max-h-[90dvh] max-w-lg flex-col">
        <DialogHeader className="shrink-0 pr-12">
          <div className="flex min-w-0 items-start gap-3">
            <PluginIcon iconId={pluginIcon || 'lucide:package'} className="mt-0.5 h-9 w-9 shrink-0" />
            <div className="min-w-0 space-y-1.5">
              <DialogTitle className="wrap-break-word leading-7">
                {t(mode === 'trust' ? 'plugins.trust.title' : `settings.marketplace.consent.title.${mode}`, { name: pluginName })}
              </DialogTitle>
              <DialogDescription>{t(mode === 'trust' ? 'settings.marketplace.consent.trustDescription' : 'settings.marketplace.consent.installDescription')}</DialogDescription>
              {!official || mode === 'sideload' ? <p className="text-xs text-muted-foreground">{t('settings.marketplace.consent.thirdParty')}</p> : null}
            </div>
          </div>
        </DialogHeader>
        <div className="min-h-0 space-y-5 overflow-y-auto px-6 pb-3 pt-2">
          {mode === 'sideload' ? <p role="note" className="pl-12 text-sm leading-relaxed text-muted-foreground">{t('settings.marketplace.consent.sideloadWarning')}</p> : null}
          {showRuntimeNotice ? <PluginRuntimeAccessNotice
            description={t('plugins.trust.nativeAccess')}
            title={mode === 'trust' ? t('plugins.trust.noticeTitle') : undefined}
          /> : null}
          {isUpdate ? <div className="space-y-3">
            <p className="pl-12 text-sm font-medium">{t('settings.marketplace.consent.updateNewLede')}</p>
            <PluginCapabilityList capabilities={newCapabilities ?? []} highlight />
          </div> : null}
          {statusMessage ? <p role="status" className="pl-12 text-sm text-muted-foreground">{statusMessage}</p>
            : <section className="space-y-3" aria-label={t('settings.marketplace.consent.declaredUses')}>
              <h3 className="pl-12 text-sm font-medium">{t('settings.marketplace.consent.declaredUses')}</h3>
              <PluginCapabilityList capabilities={capabilities} />
            </section>}
          <details className="group pl-12">
            <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-2 rounded-sm py-1 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
              {t('settings.marketplace.consent.details')}
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
            </summary>
            <div className="space-y-3 pt-4">
              <p className="text-sm">v{version}</p>
              {executionMode ? <p className="text-xs text-muted-foreground">{t(executionMode === 'trusted_process' ? 'settings.marketplace.plan.trustedMode' : 'settings.marketplace.plan.restrictedMode')}</p> : null}
              {nativeAccess && !showRuntimeNotice ? <p className="text-sm leading-relaxed text-muted-foreground">{t('plugins.trust.nativeAccess')}</p> : null}
              <PluginCapabilityList capabilities={capabilities} detailed />
            </div>
          </details>
        </div>
        <DialogFooter className="shrink-0 border-0 pb-6 pt-2">
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
