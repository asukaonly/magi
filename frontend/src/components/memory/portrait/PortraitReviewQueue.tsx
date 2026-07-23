import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { PortraitDisplayItem } from './portraitGrouping';
import { Button } from '@/components/ui/button';
import {
  MEMORY_GHOST_ACTION_CLASS,
  MEMORY_PRIMARY_ACTION_CLASS,
} from '@/components/memory/memoryActionStyles';

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
      className="rounded-mem-lg bg-[hsl(var(--memory-panel-elevated)/0.58)] px-6 py-6 shadow-[0_14px_36px_hsl(var(--memory-shadow)/0.035)] sm:px-7"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
          {t('memory.portrait.review.title')}
        </h2>
        <span className="text-sm tabular-nums text-[hsl(var(--memory-muted))]">
          {t('memory.portrait.review.count', { count: items.length })}
        </span>
      </div>

      <div className="mt-5 space-y-5">
        {items.map((item) => {
          const source = sourceText(item, t);
          const isConfirming = item.assertionId === confirmingAssertionId;
          const correctionUnavailable = !item.assertionId || item.correctionValue == null;
          return (
            <article key={item.id} className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between lg:gap-6">
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-[0.95rem] font-medium leading-7 text-[hsl(var(--memory-title))]">{item.text}</p>
                {source ? <p className="text-xs leading-5 text-[hsl(var(--memory-muted))]">{source}</p> : null}
              </div>

              <div className="flex flex-wrap items-center gap-1.5 lg:justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => item.assertionId && void onConfirm(item.assertionId)}
                    disabled={!item.assertionId || confirmingAssertionId !== null}
                    aria-busy={isConfirming}
                    className={MEMORY_PRIMARY_ACTION_CLASS}
                  >
                    {t('memory.portrait.review.actions.confirm')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => item.assertionId && onRequestCorrection(item, 'remove')}
                    disabled={correctionUnavailable || confirmingAssertionId !== null}
                    className={MEMORY_GHOST_ACTION_CLASS}
                  >
                    {t('memory.portrait.review.actions.reject')}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => item.assertionId && onRequestCorrection(item, 'replace')}
                    disabled={correctionUnavailable || confirmingAssertionId !== null}
                    className={MEMORY_GHOST_ACTION_CLASS}
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
