import { useEffect, useState } from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { pluginsApi, type PluginInstallPlan } from '@/api/modules/plugins';
import { localizedPluginText } from '@/utils/plugin-display-groups';
import { getErrorMessage } from '@/utils/error-handler';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { PluginIcon } from './PluginIcon';
import { PluginCapabilityList } from './PluginCapabilityList';
import { PluginRuntimeAccessNotice } from './PluginRuntimeAccessNotice';

interface Props {
  pluginId: string;
  update: boolean;
  connectionName?: string;
  connectionIcon?: string;
  onConfirm: (plan: PluginInstallPlan) => void;
  onCancel: () => void;
}

export function PluginRegistryPlanReview({ pluginId, update, connectionName, connectionIcon, onConfirm, onCancel }: Props) {
  const { t, i18n } = useTranslation('app');
  const [fetchedPlan, setPlan] = useState<PluginInstallPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const plan = fetchedPlan?.target_id === pluginId && fetchedPlan.update === update ? fetchedPlan : null;
  const target = plan?.changes.find(change => change.entry.plugin_id === pluginId);
  const additional = plan?.changes.filter(change => change.entry.plugin_id !== pluginId) ?? [];
  const changes = target ? [target, ...additional] : [];
  const name = connectionName || (target ? localizedPluginText(target.entry.name, target.entry.name_i18n, i18n.language) : '');
  const icon = target?.entry.icon_data || connectionIcon || target?.entry.icon;
  const nativeAccess = changes.some(change => change.entry.execution_mode === 'trusted_process');
  const showRuntimeNotice = changes.some(change => change.entry.execution_mode === 'trusted_process' && !change.entry.official);

  useEffect(() => {
    let active = true;
    setPlan(null);
    setError(null);
    void pluginsApi.getInstallPlan(pluginId, update).then((value) => {
      if (active) setPlan(value);
    }).catch((cause: unknown) => {
      if (active) setError(getErrorMessage(cause) ?? String(cause));
    });
    return () => { active = false; };
  }, [pluginId, update, attempt]);

  function reasonLabel(reason: string): string {
    if (reason === 'requested') return t('settings.marketplace.plan.reason.requested');
    const dependency = reason.startsWith('dependency of ');
    const consumer = reason.startsWith('consumer of ');
    if (dependency || consumer) {
      const id = reason.slice(dependency ? 14 : 12);
      const entry = changes.find(change => change.entry.plugin_id === id)?.entry;
      const parentName = entry ? localizedPluginText(entry.name, entry.name_i18n, i18n.language) : id;
      return t(dependency ? 'settings.marketplace.plan.reason.dependency' : 'settings.marketplace.plan.reason.consumer', { name: parentName });
    }
    return reason;
  }

  const confirmLabel = connectionName
    ? t('onboarding:pluginInstallPanel.installContinue')
    : t(update ? 'settings.marketplace.plan.confirmUpdate' : 'settings.marketplace.plan.confirm');

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <DialogContent className="flex max-h-[90dvh] max-w-lg flex-col">
        <DialogHeader className="shrink-0 pr-12">
          <div className="flex items-start gap-3">
            <PluginIcon iconId={icon || 'lucide:package'} className="mt-0.5 h-9 w-9 shrink-0" />
            <div className="min-w-0 space-y-1.5">
              <DialogTitle className="break-words leading-7">
                {connectionName ? t('onboarding:pluginInstallPanel.installTitle', { name })
                  : name ? t(update ? 'settings.marketplace.plan.updateTitle' : 'settings.marketplace.plan.title', { name })
                  : t('settings.marketplace.plan.loading')}
              </DialogTitle>
              <DialogDescription>
                {connectionName ? t('onboarding:pluginInstallPanel.installDescription')
                  : target ? localizedPluginText(target.entry.description, target.entry.description_i18n, i18n.language)
                    || t('settings.marketplace.plan.description') : t('settings.marketplace.plan.description')}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        <div className="min-h-0 space-y-5 overflow-y-auto px-6 pb-3 pt-2">
          {!plan && !error ? (
            <p role="status" className="flex items-center gap-3 text-sm text-muted-foreground">
              <span className="flex w-9 shrink-0 justify-center"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /></span>
              {t('settings.marketplace.plan.loading')}
            </p>
          ) : null}
          {error ? (
            <div role="alert" className="space-y-2 pl-12 text-sm">
              <p>{t('settings.marketplace.plan.failed', { message: error })}</p>
              <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>{t('settings.marketplace.plan.retry')}</Button>
            </div>
          ) : null}
          {showRuntimeNotice ? <PluginRuntimeAccessNotice description={t('settings.marketplace.plan.nativeAccess')} /> : null}
          {target ? <section className="space-y-3" aria-label={t('settings.marketplace.consent.declaredUses')}>
            <h3 className="pl-12 text-sm font-medium">{t('settings.marketplace.consent.declaredUses')}</h3>
            <PluginCapabilityList capabilities={target.entry.capabilities} />
          </section> : null}
          {additional.filter(change => change.entry.capabilities.length > 0).map(change => (
            <section key={change.entry.plugin_id} className="space-y-3" aria-label={t('settings.marketplace.plan.componentAccess', { name: localizedPluginText(change.entry.name, change.entry.name_i18n, i18n.language) })}>
              <h3 className="pl-12 text-sm font-medium">{t('settings.marketplace.plan.componentAccess', { name: localizedPluginText(change.entry.name, change.entry.name_i18n, i18n.language) })}</h3>
              <PluginCapabilityList capabilities={change.entry.capabilities} />
            </section>
          ))}
          {plan?.coordinated ? <p className="pl-12 text-sm leading-relaxed">{t('settings.marketplace.plan.coordinated')}</p> : null}
          {plan ? <details key={plan.fingerprint} open={plan.coordinated || update} className="group pl-12">
            <summary className="inline-flex min-h-9 cursor-pointer list-none flex-wrap items-center gap-x-2 rounded-sm py-1 text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
              <span>{t('settings.marketplace.plan.details')}</span>
              <span aria-hidden="true">·</span>
              <span>{t('settings.marketplace.plan.packageCount', { count: plan.changes.length })}</span>
              <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
            </summary>
            <div className="space-y-6 pb-2 pt-4">
              {nativeAccess && !showRuntimeNotice ? <p className="text-sm leading-relaxed text-muted-foreground">{t('settings.marketplace.plan.nativeAccess')}</p> : null}
              {changes.map(change => (
                <section key={change.entry.plugin_id} className="space-y-3" aria-label={localizedPluginText(change.entry.name, change.entry.name_i18n, i18n.language)}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                    <h3 className="break-words font-medium">{localizedPluginText(change.entry.name, change.entry.name_i18n, i18n.language)}</h3>
                    <span className="text-xs text-muted-foreground">{t(`settings.marketplace.plan.action.${change.action}`)}</span>
                  </div>
                  <p className="break-all text-xs text-muted-foreground">{change.entry.plugin_id}</p>
                  <p className="text-xs text-muted-foreground">{t(change.entry.official ? 'settings.marketplace.badge.official' : 'settings.marketplace.consent.thirdParty')}</p>
                  <p className="text-sm tabular-nums">{change.current_version ?? t('settings.marketplace.plan.notInstalled')} → {change.entry.version}</p>
                  <p className="text-xs text-muted-foreground">{reasonLabel(change.reason)}</p>
                  <p className="text-xs text-muted-foreground">{t(change.entry.execution_mode === 'trusted_process' ? 'settings.marketplace.plan.trustedMode' : 'settings.marketplace.plan.restrictedMode')}</p>
                  <p className="text-sm font-medium">{t('settings.marketplace.plan.permissions')}</p>
                  <PluginCapabilityList capabilities={change.entry.capabilities} detailed />
                </section>
              ))}
            </div>
          </details> : null}
        </div>
        <DialogFooter className="shrink-0 border-0 pb-6 pt-2">
          <Button variant="outline" onClick={onCancel}>{t('settings.marketplace.consent.cancel')}</Button>
          <Button disabled={!target || Boolean(error)} onClick={() => { if (plan && target) onConfirm(plan); }}>{confirmLabel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
