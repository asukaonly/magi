import { useTranslation } from 'react-i18next';
import { PluginIcon } from '@/components/plugins/PluginIcon';

export interface EmptyStateSensorCardProps {
  pluginId: string;
  titleKey: string;
  valueKey: string;
  iconId?: string;
  onConnect: (pluginId: string) => void;
  disabled?: boolean;
  i18nNamespace?: string;
  i18nKeyPrefix?: string;
  /**
   * i18n key for the connect button label. Defaults to `emptyState.connect`.
   * Consumers pass `emptyState.installAndConnect` for plugins that aren't yet
   * installed locally (registry install-first flow).
   */
  connectLabelKey?: string;
}

export function EmptyStateSensorCard({
  pluginId,
  titleKey,
  valueKey,
  iconId,
  onConnect,
  disabled,
  i18nNamespace = 'onboarding',
  i18nKeyPrefix,
  connectLabelKey,
}: EmptyStateSensorCardProps): JSX.Element {
  const { t } = useTranslation(i18nNamespace);
  const keyed = (key: string) => (i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key);
  return (
    <div className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-[hsl(var(--app-chrome-surface)/0.5)]">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-background/80 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.42)]">
        <PluginIcon iconId={iconId} pluginId={pluginId} className="h-4 w-4" />
      </span>
      <div className="flex min-w-0 flex-col gap-0.5">
        <h3 className="truncate text-sm font-semibold text-foreground">{t(keyed(titleKey))}</h3>
        <p className="truncate text-xs leading-5 text-muted-foreground">{t(keyed(valueKey))}</p>
      </div>
      <button
        type="button"
        data-testid={`empty-state-connect-${pluginId}`}
        onClick={() => onConnect(pluginId)}
        disabled={disabled}
        className="ml-auto shrink-0 min-w-[5.5rem] rounded-md px-3 py-1.5 text-center text-xs font-semibold text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.34)] transition-[background-color,color,box-shadow] hover:bg-primary/10 hover:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.48)] disabled:opacity-50"
      >
        {t(keyed(connectLabelKey ?? 'emptyState.connect'))}
      </button>
    </div>
  );
}
