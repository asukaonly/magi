import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { pluginsApi, type PluginInstallPlan } from '@/api/modules/plugins';
import { capabilityMeta } from '@/lib/pluginCapabilities';
import { localizedPluginText } from '@/utils/plugin-display-groups';
import { getErrorMessage } from '@/utils/error-handler';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';

interface Props {
  pluginId: string;
  update: boolean;
  onConfirm: (plan: PluginInstallPlan) => void;
  onCancel: () => void;
}

export function PluginRegistryPlanReview({ pluginId, update, onConfirm, onCancel }: Props) {
  const { t, i18n } = useTranslation('app');
  const [fetchedPlan, setPlan] = useState<PluginInstallPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const plan = fetchedPlan?.target_id === pluginId && fetchedPlan.update === update ? fetchedPlan : null;

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
    if (reason.startsWith('dependency of ')) {
      return t('settings.marketplace.plan.reason.dependency', { name: reason.slice(14) });
    }
    if (reason.startsWith('consumer of ')) {
      return t('settings.marketplace.plan.reason.consumer', { name: reason.slice(12) });
    }
    return reason;
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <DialogContent className="flex max-h-[90dvh] max-w-2xl flex-col">
        <DialogHeader>
          <DialogTitle>{t('settings.marketplace.plan.title')}</DialogTitle>
          <DialogDescription>
            {t('settings.marketplace.plan.description')}
            {plan ? <span className="mt-1 block">{t('settings.marketplace.plan.packageCount', { count: plan.changes.length })}</span> : null}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 max-h-[65vh] space-y-4 overflow-y-auto px-6 pb-3">
          {!plan && !error ? (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('settings.marketplace.plan.loading')}
            </p>
          ) : null}
          {error ? (
            <div role="alert" className="space-y-2">
              <p>{t('settings.marketplace.plan.failed', { message: error })}</p>
              <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>
                {t('settings.marketplace.plan.retry')}
              </Button>
            </div>
          ) : null}
          {plan?.coordinated ? (
            <p className="rounded-md bg-muted p-3 text-sm">{t('settings.marketplace.plan.coordinated')}</p>
          ) : null}
          {plan?.changes.map((change) => (
            <section key={change.entry.plugin_id} className="space-y-2 rounded-lg border p-4" aria-label={change.entry.name}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="break-words font-medium">
                  {localizedPluginText(change.entry.name, change.entry.name_i18n, i18n.language)}
                </h3>
                <span className="text-xs text-muted-foreground">{t(`settings.marketplace.plan.action.${change.action}`)}</span>
              </div>
              <p className="break-all text-xs text-muted-foreground">{change.entry.plugin_id}</p>
              <p className="text-sm tabular-nums">
                {change.current_version ?? t('settings.marketplace.plan.notInstalled')} → {change.entry.version}
              </p>
              <p className="break-words text-xs text-muted-foreground">{reasonLabel(change.reason)}</p>
              {change.entry.execution_mode === 'trusted_process' ? <p className="text-sm">{t('plugins.trust.nativeAccess')}</p> : null}
              <p className="text-sm font-medium">{t('settings.marketplace.plan.permissions')}</p>
              {change.entry.capabilities.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('settings.marketplace.consent.ledeEmpty')}</p>
              ) : (
                <ul className="space-y-2">
                  {change.entry.capabilities.map((capability, index) => (
                    <li key={`${capability.capability}-${index}`} className="text-sm">
                      <span className="font-medium">{t(`${capabilityMeta(capability.capability).i18nKey}.label`)}</span>
                      {capability.optional ? <span className="ml-2 text-xs text-muted-foreground">{t('settings.marketplace.plan.optional')}</span> : null}
                      <p className="break-words text-muted-foreground">
                        {capability.scope.length ? capability.scope.join(', ') : t('settings.marketplace.plan.unscoped')}
                      </p>
                      <p className="break-words text-muted-foreground">
                        {localizedPluginText(capability.reason, capability.reason_i18n, i18n.language)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>{t('settings.marketplace.consent.cancel')}</Button>
          <Button disabled={!plan || Boolean(error)} onClick={() => { if (plan) onConfirm(plan); }}>
            {t('settings.marketplace.plan.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
