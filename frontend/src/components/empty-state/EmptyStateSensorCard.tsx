import { useTranslation } from 'react-i18next';

export interface EmptyStateSensorCardProps {
  pluginId: string;
  titleKey: string;
  valueKey: string;
  iconId?: string;
  onConnect: (pluginId: string) => void;
  disabled?: boolean;
}

export function EmptyStateSensorCard({
  pluginId,
  titleKey,
  valueKey,
  iconId,
  onConnect,
  disabled,
}: EmptyStateSensorCardProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-[#e6d7c5] bg-white p-4 dark:border-[#5b4a3d] dark:bg-[#2a2018]">
      {iconId && (
        <span
          aria-hidden
          className="inline-flex h-8 w-8 items-center justify-center rounded bg-[#f4eadf] text-[#35261f] dark:bg-[#5b4a3d] dark:text-[#f4eadf]"
        >
          {/* Plain string id rendered as a single-letter fallback. Real icon
              mapping (lucide-react / asset module) can be wired in a
              follow-up task; for Plan 3 this keeps the component
              loader-free and tests asset-free. */}
          {iconId.slice(0, 1).toUpperCase()}
        </span>
      )}
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium text-[#35261f] dark:text-[#f4eadf]">
          {t(titleKey)}
        </h3>
        <p className="text-xs text-[#7d685a] dark:text-[#c8b7a7]">{t(valueKey)}</p>
      </div>
      <button
        type="button"
        data-testid={`empty-state-connect-${pluginId}`}
        onClick={() => onConnect(pluginId)}
        disabled={disabled}
        className="self-start rounded-md bg-[#35261f] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-[#f4eadf] dark:text-[#35261f]"
      >
        {t('emptyState.connect')}
      </button>
    </div>
  );
}
