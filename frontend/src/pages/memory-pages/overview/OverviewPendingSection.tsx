import { Check, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  MEMORY_ACTION_BUTTON_CLASS,
  MEMORY_SECTION_SURFACE_CLASS,
} from '../MemoryPageFrame';
import type { PendingOverviewItem } from './overviewModel';

export function OverviewPendingSection({
  items,
  actionBusyId,
  onAction,
}: {
  items: PendingOverviewItem[];
  actionBusyId: string | null;
  onAction: (item: PendingOverviewItem, action: 'confirmed' | 'rejected') => void;
}) {
  const { t } = useTranslation('app');

  return (
    <section className={MEMORY_SECTION_SURFACE_CLASS}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
          {t('memory.overview.sections.pending')}
        </h2>
        <span className="text-xs text-[hsl(var(--memory-muted))]">
          {t('memory.overview.pendingCount', { count: items.length })}
        </span>
      </div>
      <div className="mt-5 space-y-3">
        {items.map((item) => (
          <div
            key={item.id}
            className="grid gap-4 rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.46)] px-4 py-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
          >
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{item.title}</div>
              <div className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{item.body}</div>
              <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
                {item.kind === 'assertion' ? t('memory.overview.pendingKinds.assertion') : t('memory.overview.pendingKinds.story')}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className={MEMORY_ACTION_BUTTON_CLASS}
                aria-label={item.kind === 'assertion' ? t('memory.overview.actions.confirmAssertion') : t('memory.overview.actions.confirmStory')}
                disabled={actionBusyId === item.id}
                onClick={() => onAction(item, 'confirmed')}
              >
                <Check className="mr-1 h-3.5 w-3.5" />
                {t('memory.overview.actions.confirm')}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className={MEMORY_ACTION_BUTTON_CLASS}
                aria-label={item.kind === 'assertion' ? t('memory.overview.actions.rejectAssertion') : t('memory.overview.actions.rejectStory')}
                disabled={actionBusyId === item.id}
                onClick={() => onAction(item, 'rejected')}
              >
                <X className="mr-1 h-3.5 w-3.5" />
                {t('memory.overview.actions.reject')}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
