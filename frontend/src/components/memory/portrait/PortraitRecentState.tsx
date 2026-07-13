import { useTranslation } from 'react-i18next';
import type { PortraitDisplayItem } from './portraitGrouping';

interface PortraitRecentStateProps {
  items: PortraitDisplayItem[];
}

export const PortraitRecentState = ({ items }: PortraitRecentStateProps) => {
  const { t } = useTranslation('app');

  if (items.length === 0) {
    return null;
  }

  return (
    <section
      data-testid="portrait-recent-state"
      className="rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-5 py-4"
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.portrait.recent.title')}
        </h2>
        <p className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.portrait.recent.meta')}</p>
      </div>

      <div className="mt-3 divide-y divide-[hsl(var(--memory-divider)/0.68)]">
        {items.slice(0, 6).map((item) => (
          <article key={item.id} className="py-3">
            <p className="text-sm leading-6 text-[hsl(var(--memory-title))]">
              {item.claimKind
                ? t(`memory.portrait.recent.kinds.${item.claimKind}`, {
                    value: item.text,
                    defaultValue: item.text,
                  })
                : item.text}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
};

export default PortraitRecentState;
