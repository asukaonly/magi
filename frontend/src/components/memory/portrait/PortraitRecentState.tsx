import { PortraitEvidenceLabel, portraitItemText } from './PortraitEvidenceLabel';
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
    <section data-testid="portrait-recent-state">
      <header className="flex items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.portrait.recent.title')}
        </h2>
        <p className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.portrait.recent.meta')}</p>
      </header>

      <div className="mt-3 max-w-3xl">
        {items.slice(0, 6).map((item) => (
          <article key={item.id} className="py-2.5">
            <p className="text-sm leading-7 text-[hsl(var(--memory-body))]">
              {item.expression ? portraitItemText(item, t) : item.claimKind
                ? t(`memory.portrait.recent.kinds.${item.claimKind}`, {
                    value: item.text,
                    defaultValue: item.text,
                  })
                : item.text}
            </p>
            <PortraitEvidenceLabel item={item} />
          </article>
        ))}
      </div>
    </section>
  );
};

export default PortraitRecentState;
