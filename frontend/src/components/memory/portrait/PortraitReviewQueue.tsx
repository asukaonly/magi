import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { PortraitDisplayItem } from './portraitGrouping';
import { Button } from '@/components/ui/button';

interface PortraitReviewQueueProps {
  items: PortraitDisplayItem[];
  onConfirm: (assertionId: string) => Promise<void>;
  confirmingAssertionId?: string | null;
  onRequestCorrection: (item: PortraitDisplayItem, action: 'replace' | 'remove') => void;
}

const sourceText = (item: PortraitDisplayItem, t: TFunction<'app'>): string | null => {
  if (!item.source) {
    return null;
  }
  const source = item.sourceKey
    ? t(`memory.portrait.sources.${item.sourceKey}`, { defaultValue: item.source })
    : item.source;
  return t('memory.portrait.review.source', {
    source,
  });
};

export const PortraitReviewQueue = ({
  items,
  onConfirm,
  confirmingAssertionId = null,
  onRequestCorrection,
}: PortraitReviewQueueProps) => {
  const { t } = useTranslation('app');

  if (items.length === 0) {
    return null;
  }

  return (
    <section
      data-testid="portrait-review-queue"
      className="rounded-2xl bg-[hsl(var(--memory-panel-elevated)/0.58)] px-5 py-5 shadow-[0_14px_36px_hsl(var(--memory-shadow)/0.035)] sm:px-6"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
          {t('memory.portrait.review.title')}
        </h2>
        <span className="text-sm text-[hsl(var(--memory-muted))]">
          {t('memory.portrait.review.count', { count: items.length })}
        </span>
      </div>

      <div className="mt-4 space-y-2">
        {items.map((item) => {
          const source = sourceText(item, t);
          const isConfirming = item.assertionId === confirmingAssertionId;
          return (
            <article key={item.id} className="flex flex-col gap-4 rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.34)] px-4 py-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-sm font-medium leading-6 text-[hsl(var(--memory-title))]">{item.text}</p>
                {source ? <p className="text-xs text-[hsl(var(--memory-muted))]">{source}</p> : null}
              </div>

              <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => item.assertionId && void onConfirm(item.assertionId)}
                    disabled={!item.assertionId || confirmingAssertionId !== null}
                    aria-busy={isConfirming}
                    className="min-h-9 rounded-lg px-3 text-[hsl(var(--memory-title))]"
                  >
                    {t('memory.portrait.review.actions.confirm')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => item.assertionId && onRequestCorrection(item, 'remove')}
                    disabled={!item.assertionId || confirmingAssertionId !== null}
                    className="min-h-9 rounded-lg px-3 text-[hsl(var(--memory-body))]"
                  >
                    {t('memory.portrait.review.actions.reject')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => item.assertionId && onRequestCorrection(item, 'replace')}
                    disabled={!item.assertionId || confirmingAssertionId !== null}
                    className="min-h-9 rounded-lg px-3 text-[hsl(var(--memory-body))]"
                  >
                    {t('memory.portrait.review.actions.edit')}
                  </Button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
};

export default PortraitReviewQueue;
