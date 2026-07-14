import { useTranslation } from 'react-i18next';
import type { PortraitWorldGroup } from './portraitGrouping';

interface PortraitWorldMapProps {
  groups: PortraitWorldGroup[];
  totalCount: number;
}

export const PortraitWorldMap = ({ groups, totalCount }: PortraitWorldMapProps) => {
  const { t } = useTranslation('app');
  const visibleGroups = groups.filter((group) => group.summary || group.items.length > 0);

  return (
    <section
      data-testid="portrait-world-map"
      className="pt-3"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <h1 className="text-[clamp(1.7rem,2.8vw,2.25rem)] font-semibold tracking-[-0.035em] text-[hsl(var(--memory-title))]">
          {t('memory.portrait.world.title')}
        </h1>
        {totalCount > 0 ? (
          <p className="pb-1 text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.portrait.world.meta', { count: totalCount })}
          </p>
        ) : null}
      </div>

      {visibleGroups.length > 0 ? (
        <div className="mt-12">
          <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
            {t('memory.portrait.world.summaryTitle')}
          </h2>
          <div className="mt-8 grid gap-x-14 gap-y-10 md:grid-cols-2" data-testid="portrait-world-groups">
            {visibleGroups.map((group) => (
              <article
                key={group.id}
                data-testid={`portrait-world-branch-${group.id}`}
                className="min-w-0"
              >
                <h3 className="text-xs font-semibold text-[hsl(var(--memory-muted))]">
                  {t(`memory.portrait.world.groups.${group.id}`)}
                </h3>
                <div className="mt-3 space-y-3">
                  {group.summary ? (
                    <p className="text-[0.95rem] font-medium leading-7 text-[hsl(var(--memory-title))]">
                      {group.summary}
                    </p>
                  ) : (
                    group.items.slice(0, 4).map((item) => (
                      <p key={item.id} className="text-[0.95rem] leading-7 text-[hsl(var(--memory-title))]">
                        {item.text}
                      </p>
                    ))
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
};

export default PortraitWorldMap;
