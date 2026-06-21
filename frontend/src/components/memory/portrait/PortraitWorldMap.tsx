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
      className="rounded-2xl bg-[hsl(var(--memory-panel-elevated)/0.78)] px-5 py-5 shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.28),0_18px_48px_-42px_hsl(var(--memory-shadow)/0.52)]"
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
        className="mt-5 overflow-hidden rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.32)] px-4 py-4 lg:px-5 lg:py-5"
      >
        <div className="grid gap-4 lg:grid-cols-[176px_minmax(0,1fr)]">
          <div
            data-testid="portrait-world-root"
            className="flex items-center gap-3 rounded-xl bg-[hsl(var(--memory-accent-soft)/0.42)] px-4 py-4 shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.18)] lg:self-start lg:flex-col lg:items-start"
          >
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--memory-panel-elevated)/0.92)] text-sm font-semibold text-[hsl(var(--memory-accent))] shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.34)]">
              {t('memory.portrait.world.rootLabel')}
            </span>
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                {t('memory.portrait.world.rootTitle')}
              </p>
              <p className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                {t('memory.portrait.world.rootMeta')}
              </p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {groups.map((group) => (
              <article
                key={group.id}
                data-testid={`portrait-world-branch-${group.id}`}
                className="group rounded-xl bg-[hsl(var(--memory-panel-elevated)/0.76)] px-4 py-4 shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.24)] transition-colors duration-200 hover:bg-[hsl(var(--memory-panel-elevated)/0.94)]"
              >
                <div className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-1 h-7 w-1 shrink-0 rounded-full bg-[hsl(var(--memory-accent)/0.24)] transition-colors duration-200 group-hover:bg-[hsl(var(--memory-accent)/0.36)]"
                  />
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                      {t(`memory.portrait.world.groups.${group.id}`)}
                    </h3>

                    <div className="mt-3 space-y-3">
                      {group.items.length === 0 ? (
                        <p className="text-sm leading-6 text-[hsl(var(--memory-muted))]">
                          {t('memory.portrait.world.empty')}
                        </p>
                      ) : (
                        group.items.slice(0, 4).map((item) => (
                          <div key={item.id} className="space-y-1">
                            <p className="text-sm leading-6 text-[hsl(var(--memory-title))]">
                              {item.text}
                            </p>
                            <p className="text-xs text-[hsl(var(--memory-muted))]">
                              {sourceText(item, t)}
                            </p>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
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
