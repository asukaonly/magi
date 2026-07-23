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
      className="px-1 py-1"
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
          {t('memory.portrait.recent.title')}
        </h2>
        <p className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.portrait.recent.meta')}</p>
      </div>

      <div className="mt-6 max-w-3xl space-y-5">
        {items.slice(0, 6).map((item) => (
          <article key={item.id}>
            <p className="text-sm leading-8 text-[hsl(var(--memory-title))]">
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
