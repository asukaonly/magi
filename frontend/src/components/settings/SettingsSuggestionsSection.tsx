import { useTranslation } from 'react-i18next';

import { useSuggestionDismissals } from '@/hooks/useSuggestionDismissals';

/**
 * Settings section listing the user's active system-suggestion dismissals and
 * letting them restore (clear) one so its suggestion can surface again.
 */
export function SettingsSuggestionsSection(): JSX.Element {
  const { t } = useTranslation('app');
  const { items, clear, loading } = useSuggestionDismissals();

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">{t('settings.suggestions.title')}</h2>
      <p className="text-sm text-muted-foreground">{t('settings.suggestions.description')}</p>
      {!loading && items.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('settings.suggestions.empty')}</p>
      )}
      {items.length > 0 && (
        <ul className="divide-y divide-border/55 rounded-md border border-border/55">
          {items.map((d) => (
            <li key={d.dedupe_key} className="flex items-center justify-between px-4 py-3">
              <div>
                <div className="text-sm font-medium text-foreground">{d.dedupe_key}</div>
                <div className="text-xs text-muted-foreground">{d.kind}</div>
              </div>
              <button
                type="button"
                onClick={() => void clear(d.dedupe_key)}
                className="rounded-md border border-border/55 px-3 py-1.5 text-xs"
              >
                {t('settings.suggestions.restore')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default SettingsSuggestionsSection;
