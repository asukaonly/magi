import { CircleHelp, icons, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { PluginCapability } from '@/api/modules/plugins';
import { capabilityMeta, capabilityScopeKey } from '@/lib/pluginCapabilities';
import { localizedPluginText } from '@/utils/plugin-display-groups';
import { cn } from '@/lib/utils';

interface Props {
  capabilities: PluginCapability[];
  detailed?: boolean;
  highlight?: boolean;
}

/** Keep access purposes visible; reserve filesystem paths for the detailed review. */
export function PluginCapabilityList({ capabilities, detailed = false, highlight = false }: Props) {
  const { t, i18n } = useTranslation('app');
  if (capabilities.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('settings.marketplace.consent.ledeEmpty')}</p>;
  }
  return <ul className="space-y-3">
    {capabilities.map((capability, index) => {
      const meta = capabilityMeta(capability.capability);
      const Icon: LucideIcon = icons[meta.icon as keyof typeof icons] ?? CircleHelp;
      const reason = localizedPluginText(capability.reason, capability.reason_i18n, i18n.language)
        || t(`${meta.i18nKey}.desc`);
      const showScopes = detailed || !meta.known || ['network', 'memory_search', 'interaction_ask'].includes(capability.capability);
      return <li key={`${capability.capability}-${index}`} className={cn('flex gap-3 text-sm', highlight && 'rounded-md bg-primary/5 p-3')}>
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">{meta.known ? t(`${meta.i18nKey}.label`) : capability.capability}</span>
            {capability.optional ? <span className="text-xs text-muted-foreground">{t('settings.marketplace.consent.optionalTag')}</span> : null}
          </div>
          <p className="break-words leading-relaxed text-muted-foreground">{reason}</p>
          {showScopes ? capability.scope.length > 0 ? capability.scope.map(scope => {
            const key = capabilityScopeKey(capability.capability, scope);
            return <code key={scope} className="block whitespace-normal text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{key ? t(key) : scope}</code>;
          }) : detailed ? <p className="text-xs text-muted-foreground">{t('settings.marketplace.plan.unscoped')}</p> : null : null}
        </div>
      </li>;
    })}
  </ul>;
}
