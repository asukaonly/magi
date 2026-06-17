import { useTranslation } from 'react-i18next';
import { PluginIcon } from '@/components/plugins/PluginIcon';

export interface EmptyStateSensorCardProps {
  pluginId: string;
  titleKey: string;
  valueKey: string;
  iconId?: string;
  onConnect: (pluginId: string) => void;
  disabled?: boolean;
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
  connectLabelKey,
}: EmptyStateSensorCardProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border/60 bg-background/80">
        <PluginIcon iconId={iconId} pluginId={pluginId} className="h-4 w-4" />
      </span>
      <div className="flex min-w-0 flex-col gap-0.5">
        <h3 className="truncate text-sm font-medium text-foreground">{t(titleKey)}</h3>
        <p className="truncate text-xs text-muted-foreground">{t(valueKey)}</p>
      </div>
      <button
        type="button"
        data-testid={`empty-state-connect-${pluginId}`}
        onClick={() => onConnect(pluginId)}
        disabled={disabled}
        className="ml-auto shrink-0 min-w-[5.5rem] rounded-md border border-primary/40 px-3 py-1.5 text-center text-xs font-medium text-primary transition hover:bg-primary/10 disabled:opacity-50"
      >
        {t(connectLabelKey ?? 'emptyState.connect')}
      </button>
    </div>
  );
}
