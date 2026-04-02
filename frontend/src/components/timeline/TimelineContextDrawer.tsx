import React from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { TimelineContextBundle } from '@/api/modules/timeline';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface TimelineContextDrawerProps {
  selectedAnchorId: string | null;
  loading: boolean;
  contextBundle: TimelineContextBundle | null;
  onClose?: () => void;
}

export const TimelineContextDrawer: React.FC<TimelineContextDrawerProps> = ({
  selectedAnchorId,
  loading,
  contextBundle,
  onClose,
}) => {
  const { t } = useTranslation('app');

  return (
    <aside className="hidden min-h-0 border-l border-border/60 xl:block">
      <div className="h-full overflow-y-auto px-5 py-5">
        {selectedAnchorId == null ? (
          <p className="py-8 text-center text-sm text-muted-foreground/60">
            {t('timeline.drawer.empty')}
          </p>
        ) : loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <LoadingSpinner className="h-4 w-4" />
            {t('timeline.feed.loadingDetails')}
          </div>
        ) : contextBundle ? (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-foreground">{contextBundle.anchor.title}</h2>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                  {contextBundle.anchor.summary}
                </p>
              </div>
              {onClose && (
                <button onClick={onClose} className="shrink-0 text-muted-foreground/50 hover:text-foreground">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {(contextBundle.l3_reflections || []).length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t('timeline.drawer.reflections')}
                </h3>
                {contextBundle.l3_reflections.map((reflection, i) => (
                  <div
                    key={`${(reflection as Record<string, unknown>).summary_id || i}`}
                    className="rounded-md bg-muted/40 px-3 py-2.5 text-sm text-muted-foreground"
                  >
                    {String((reflection as Record<string, unknown>).content || '')}
                  </div>
                ))}
              </section>
            )}

            {(contextBundle.l4_related_procedures || []).length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t('timeline.drawer.procedures')}
                </h3>
                {contextBundle.l4_related_procedures.map((proc, i) => (
                  <div
                    key={`${(proc as Record<string, unknown>).skill_id || i}`}
                    className="text-sm text-foreground"
                  >
                    {String((proc as Record<string, unknown>).skill_name || '')}
                  </div>
                ))}
              </section>
            )}
          </div>
        ) : null}
      </div>
    </aside>
  );
};

export default TimelineContextDrawer;
