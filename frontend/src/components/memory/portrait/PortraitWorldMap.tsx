import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { PortraitDisplayItem, PortraitWorldGroup } from './portraitGrouping';

interface PortraitWorldMapProps {
  groups: PortraitWorldGroup[];
  totalCount: number;
  onCorrect: (item: PortraitDisplayItem) => void;
}

export const PortraitWorldMap = ({ groups, totalCount, onCorrect }: PortraitWorldMapProps) => {
  const { t } = useTranslation('app');
  const visibleGroups = groups.filter((group) => group.summary || group.items.length > 0);

  return (
    <section
      data-testid="portrait-world-map"
    >
      {visibleGroups.length > 0 ? (
        <div>
          <header className="flex items-baseline justify-between gap-4">
            <h2 className="text-[13px] font-semibold text-[hsl(var(--memory-title))]">
              {t('memory.portrait.world.summaryTitle')}
            </h2>
            {totalCount > 0 ? (
              <p className="text-xs tabular-nums text-[hsl(var(--memory-muted))]">
                {t('memory.portrait.world.meta', { count: totalCount })}
              </p>
            ) : null}
          </header>
          <div className="mt-6 grid gap-x-14 gap-y-10 md:grid-cols-2" data-testid="portrait-world-groups">
            {visibleGroups.map((group) => {
              const detailItems = group.summary ? group.items : group.items.slice(4);
              return (
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
                    <p className="text-[1.05rem] font-medium leading-8 text-[hsl(var(--memory-title))]">
                      {group.summary}
                    </p>
                  ) : (
                    group.items.slice(0, 4).map((item) => (
                      <div key={item.id} className="group flex items-start justify-between gap-3">
                        <p className="min-w-0 flex-1 text-[0.95rem] leading-7 text-[hsl(var(--memory-title))]">{item.text}</p>
                        {item.assertionId && item.correctionValue != null ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="min-h-9 shrink-0 rounded-mem-sm px-2.5 text-[hsl(var(--memory-body))] opacity-0 transition-opacity hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))] focus-visible:opacity-100 group-hover:opacity-100"
                            onClick={() => onCorrect(item)}
                            aria-label={t('memory.portrait.world.correctItem', { defaultValue: '修正 {{value}}', value: item.text })}
                          >
                            {t('memory.portrait.world.correct', { defaultValue: '修正' })}
                          </Button>
                        ) : null}
                      </div>
                    ))
                  )}
                  {detailItems.length > 0 ? (
                    <details className="group/details pt-1">
                      <summary className="flex min-h-9 cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-[hsl(var(--memory-muted))] outline-none transition-colors duration-200 hover:text-[hsl(var(--memory-title))] focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]">
                        {t('memory.portrait.world.inspectItems', {
                          defaultValue: '查看 {{count}} 条具体信息',
                          count: detailItems.length,
                        })}
                        <ChevronDown className="h-3.5 w-3.5 transition-transform group-open/details:rotate-180" aria-hidden="true" />
                      </summary>
                      <div className="mt-2 space-y-2">
                        {detailItems.map((item) => (
                          <div key={item.id} className="group flex items-start justify-between gap-3 rounded-mem-sm bg-[hsl(var(--memory-panel-subtle)/0.32)] px-3 py-2.5">
                            <p className="min-w-0 flex-1 text-sm leading-6 text-[hsl(var(--memory-title))]">{item.text}</p>
                            {item.assertionId && item.correctionValue != null ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="min-h-9 shrink-0 rounded-mem-sm px-2.5 text-[hsl(var(--memory-body))] opacity-0 transition-opacity hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))] focus-visible:opacity-100 group-hover:opacity-100"
                                onClick={() => onCorrect(item)}
                                aria-label={t('memory.portrait.world.correctItem', { defaultValue: '修正 {{value}}', value: item.text })}
                              >
                                {t('memory.portrait.world.correct', { defaultValue: '修正' })}
                              </Button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>
                </article>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
};

export default PortraitWorldMap;
