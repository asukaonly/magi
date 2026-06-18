import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { PortraitDisplayItem, PortraitWorldGroup } from './portraitGrouping';
import { cn } from '@/lib/utils';

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

      <div className="mt-5 grid gap-3 xl:grid-cols-2">
        {groups.map((group, index) => (
          <article
            key={group.id}
            className="rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.42)] px-4 py-4"
          >
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[hsl(var(--memory-border)/0.72)] text-xs font-semibold text-[hsl(var(--memory-accent))]',
                  'bg-[hsl(var(--memory-panel-elevated)/0.84)]'
                )}
              >
                {index + 1}
              </span>
              <h3 className="text-sm font-semibold text-[hsl(var(--memory-title))]">
                {t(`memory.portrait.world.groups.${group.id}`)}
              </h3>
            </div>

            <div className="mt-3 space-y-2 border-l border-[hsl(var(--memory-divider)/0.72)] pl-4">
              {group.items.length === 0 ? (
                <p className="text-sm text-[hsl(var(--memory-muted))]">
                  {t('memory.portrait.world.empty')}
                </p>
              ) : (
                group.items.slice(0, 4).map((item) => (
                  <div key={item.id} className="space-y-1 rounded-lg px-1 py-1">
                    <p className="text-sm leading-6 text-[hsl(var(--memory-title))]">{item.text}</p>
                    <p className="text-xs text-[hsl(var(--memory-muted))]">{sourceText(item, t)}</p>
                  </div>
                ))
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
};

export default PortraitWorldMap;
