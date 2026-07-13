import { CheckCircle2, Clock3, HardDrive } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { PluginIcon } from '@/components/plugins/PluginIcon';
import { cn } from '@/lib/utils';

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
  variant?: 'standard' | 'featured' | 'compact';
  reason?: string;
  scope?: string;
  localityLabel?: string;
  setupTimeLabel?: string;
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
  variant = 'standard',
  reason,
  scope,
  localityLabel,
  setupTimeLabel,
}: EmptyStateSensorCardProps): JSX.Element {
  const { t } = useTranslation(i18nNamespace);
  const keyed = (key: string) => (i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key);
  const isFeatured = variant === 'featured';
  const isFirstContext = variant !== 'standard';

  return (
    <div
      data-testid={isFeatured ? `empty-state-featured-${pluginId}` : undefined}
      className={cn(
        'transition-colors',
        variant === 'standard' &&
          'grid grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-4 px-4 py-3.5 hover:bg-[hsl(var(--app-chrome-surface)/0.5)]',
        isFeatured &&
          'relative grid items-center gap-4 rounded-xl border border-primary/25 bg-primary/[0.045] p-4 shadow-[0_10px_30px_-24px_hsl(var(--primary)/0.55)] sm:grid-cols-[3rem_minmax(0,1fr)_auto]',
        variant === 'compact' &&
          'grid min-w-0 grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border/45 bg-[hsl(var(--app-chrome-elevated)/0.32)] p-3.5 hover:bg-[hsl(var(--app-chrome-surface)/0.5)]',
      )}
    >
      {isFeatured ? (
        <span className="absolute -top-3 left-4 rounded-full border border-primary/20 bg-background px-2.5 py-1 text-[11px] font-semibold text-primary shadow-sm">
          {t(keyed('emptyState.recommended'))}
        </span>
      ) : null}
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-background/90 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.42)]">
        <PluginIcon iconId={iconId} pluginId={pluginId} className="h-6 w-6" />
      </span>
      <div
        className={cn(
          'flex min-w-0 flex-col',
          isFirstContext ? 'gap-1.5' : 'gap-0.5',
        )}
      >
        <h3
          className={cn(
            'font-semibold text-foreground',
            isFeatured ? 'text-base' : 'truncate text-sm',
          )}
        >
          {t(keyed(titleKey))}
        </h3>
        <p
          className={cn(
            'text-muted-foreground',
            isFirstContext ? 'text-xs leading-5' : 'truncate text-xs leading-5',
          )}
        >
          {t(keyed(valueKey))}
        </p>
        {isFeatured && reason ? (
          <p className="flex items-center gap-1.5 text-xs leading-5 text-foreground/75">
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-primary" />
            {reason}
          </p>
        ) : null}
        {isFirstContext ? (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            {scope ? (
              <span className="rounded-full bg-background/75 px-2 py-0.5 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.35)]">
                {scope}
              </span>
            ) : null}
            {localityLabel ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-background/75 px-2 py-0.5 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.35)]">
                <HardDrive className="h-3 w-3" />
                {localityLabel}
              </span>
            ) : null}
            {setupTimeLabel ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-background/75 px-2 py-0.5 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.35)]">
                <Clock3 className="h-3 w-3" />
                {setupTimeLabel}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        data-testid={`empty-state-connect-${pluginId}`}
        onClick={() => onConnect(pluginId)}
        disabled={disabled}
        className={cn(
          'shrink-0 rounded-md border px-3 py-1.5 text-center text-xs font-semibold transition-[background-color,border-color,color] disabled:opacity-50',
          isFeatured
            ? 'border-primary bg-primary text-primary-foreground hover:bg-primary/90'
            : 'border-primary/30 bg-background text-primary hover:border-primary/50 hover:bg-primary/10',
        )}
      >
        {t(keyed(connectLabelKey ?? 'emptyState.connect'))}
      </button>
    </div>
  );
}
