import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { PortraitDisplayItem, PortraitWorldGroup } from './portraitGrouping';

interface PortraitWorldMapProps {
  groups: PortraitWorldGroup[];
  totalCount: number;
}

const sourceText = (item: PortraitDisplayItem, t: TFunction<'app'>) => {
  if (!item.source) {
    return t('memory.portrait.source.default');
  }
  return item.sourceKey
    ? t(`memory.portrait.sources.${item.sourceKey}`, { defaultValue: item.source })
    : item.source;
};

export const PortraitWorldMap = ({ groups, totalCount }: PortraitWorldMapProps) => {
  const { t } = useTranslation('app');

  return (
    <section
      data-testid="portrait-world-map"
      className="rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-5 py-5"
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-xl font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.portrait.world.title')}
        </h2>
        <p className="text-sm text-[hsl(var(--memory-muted))]">
          {t('memory.portrait.world.meta', { count: totalCount })}
        </p>
      </div>

      <div
        data-testid="portrait-world-tree"
        className="relative mt-6 overflow-hidden rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.32)] px-4 py-4 lg:px-6 lg:py-6"
      >
        <div className="relative grid gap-5 lg:grid-cols-[220px_72px_minmax(0,1fr)] lg:items-center">
          <div
            data-testid="portrait-world-root"
            className="flex justify-start lg:justify-end lg:pr-0"
          >
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--memory-accent-soft)/0.86)] text-base font-semibold text-[hsl(var(--memory-accent))]">
              {t('memory.portrait.world.rootLabel')}
            </span>
          </div>

          <div aria-hidden="true" className="relative hidden h-full min-h-[360px] lg:block">
            <span
              data-testid="portrait-world-root-connector"
              className="absolute -left-5 top-1/2 h-px w-5 bg-[hsl(var(--memory-divider)/0.84)]"
            />
          </div>

          <div className="grid gap-5">
            {groups.map((group, index) => (
              <article
                key={group.id}
                data-testid={`portrait-world-branch-${group.id}`}
                className="relative py-1 pl-6"
              >
                {index < groups.length - 1 ? (
                  <span
                    aria-hidden="true"
                    data-testid="portrait-world-trunk-segment"
                    className="absolute -bottom-[35px] -left-[93px] top-[15px] hidden w-px bg-[hsl(var(--memory-divider)/0.84)] lg:block"
                  />
                ) : null}
                <span aria-hidden="true" className="absolute -left-[92px] top-[15px] hidden h-px w-[92px] bg-[hsl(var(--memory-divider)/0.84)] lg:block" />
                <span className="absolute -left-[5px] top-2.5 h-2.5 w-2.5 rounded-full bg-[hsl(var(--memory-accent)/0.82)] ring-4 ring-[hsl(var(--memory-panel-elevated)/0.92)] lg:-left-[97px]" />
                <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                  {t(`memory.portrait.world.groups.${group.id}`)}
                </h3>

                <div className="mt-3 space-y-3">
                  {group.items.length === 0 ? (
                    <p className="text-sm text-[hsl(var(--memory-muted))]">
                      {t('memory.portrait.world.empty')}
                    </p>
                  ) : (
                    group.items.slice(0, 4).map((item) => (
                      <div key={item.id} className="space-y-1">
                        <p className="text-sm leading-6 text-[hsl(var(--memory-title))]">{item.text}</p>
                        <p className="text-xs text-[hsl(var(--memory-muted))]">{sourceText(item, t)}</p>
                      </div>
                    ))
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

export default PortraitWorldMap;
