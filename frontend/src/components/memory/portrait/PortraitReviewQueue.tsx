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
    <section data-testid="portrait-review-queue">
      <header className="flex items-baseline justify-between gap-4">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-[hsl(var(--memory-title))]">
          <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-[hsl(var(--memory-accent))]" />
          {t('memory.portrait.review.title')}
        </h2>
        <span className="shrink-0 text-xs tabular-nums text-[hsl(var(--memory-muted))]">
          {t('memory.portrait.review.count', { count: items.length })}
        </span>
      </header>

      <div>
        {items.map((item) => {
          const source = sourceText(item, t);
          const isConfirming = item.assertionId === confirmingAssertionId;
          const correctionUnavailable = !item.assertionId || item.correctionValue == null;
          return (
            <article
              key={item.id}
              className="grid gap-3 py-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-8"
            >
              <div className="min-w-0">
                <p className="text-[15px] font-medium leading-7 text-[hsl(var(--memory-title))]">{item.text}</p>
                {source ? <p className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">{source}</p> : null}
              </div>

              <div className="flex flex-wrap items-center gap-1 md:justify-self-end">
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
