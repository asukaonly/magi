import { Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function PluginRuntimeAccessNotice({ description }: { description: string }) {
  const { t } = useTranslation('app');
  return (
    <div className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-3 rounded-lg bg-muted/70 py-4 pr-4 text-sm">
      <Info className="mt-0.5 h-4 w-4 justify-self-center text-muted-foreground" aria-hidden="true" />
      <div className="space-y-1.5">
        <p className="font-medium">{t('settings.marketplace.plan.executionAccess')}</p>
        <p className="break-words leading-relaxed text-foreground/75">{description}</p>
      </div>
    </div>
  );
}
