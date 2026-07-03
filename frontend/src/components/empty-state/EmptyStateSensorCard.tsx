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
    <div className="grid grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-4 px-4 py-3.5 transition-colors hover:bg-[hsl(var(--app-chrome-surface)/0.5)]">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-background/90 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.42)]">
        <PluginIcon iconId={iconId} pluginId={pluginId} className="h-6 w-6" />
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
        className="shrink-0 rounded-md border border-primary/30 bg-background px-3 py-1.5 text-center text-xs font-semibold text-primary transition-[background-color,border-color,color] hover:border-primary/50 hover:bg-primary/10 disabled:opacity-50"
      >
        {t(keyed(connectLabelKey ?? 'emptyState.connect'))}
      </button>
    </div>
  );
}
