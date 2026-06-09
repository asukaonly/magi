import { useTranslation } from 'react-i18next';

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
  // `iconId` is intentionally accepted-but-unused: plugins don't ship real
  // icons yet, so the placeholder slot was removed. Kept on the props so
  // callers (and forward-compat) don't break.
  onConnect,
  disabled,
  connectLabelKey,
}: EmptyStateSensorCardProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  return (
    // One row per item: title + one-line value on the left, action on the right.
    // Plugins don't ship real icons yet; the single-letter placeholder read as
    // visual noise, so the icon slot is intentionally not rendered. `iconId` is
    // kept on the props for callers/forward-compat.
    <div className="flex items-center gap-3 px-4 py-3">
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
