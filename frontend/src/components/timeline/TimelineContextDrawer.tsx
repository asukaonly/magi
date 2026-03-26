import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineContextBundle } from '@/api/modules/timeline';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface TimelineContextDrawerProps {
  selectedAnchorId: string | null;
  loading: boolean;
  contextBundle: TimelineContextBundle | null;
}

export const TimelineContextDrawer: React.FC<TimelineContextDrawerProps> = ({
  selectedAnchorId,
  loading,
  contextBundle,
}) => {
  const { t } = useTranslation('app');

  return (
    <aside className="hidden min-h-0 border-l border-border/60 bg-muted/10 xl:block">
      <div className="h-full overflow-y-auto px-5 py-5">
        {selectedAnchorId == null ? (
          <div className="rounded-2xl border border-dashed border-border/60 px-4 py-8 text-sm text-muted-foreground">
            {t('timeline.drawer.empty')}
          </div>
        ) : loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoadingSpinner className="h-4 w-4" />
            {t('timeline.feed.loadingDetails')}
          </div>
        ) : contextBundle ? (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-foreground">{contextBundle.anchor.title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{contextBundle.anchor.summary}</p>
            </div>

            <section className="space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">{t('timeline.drawer.reflections')}</h3>
              {(contextBundle.l3_reflections || []).map((reflection, index) => (
                <div key={`${reflection.summary_id || index}`} className="rounded-xl border border-border/60 px-3 py-3 text-sm text-muted-foreground">
                  {String(reflection.content || '')}
                </div>
              ))}
            </section>

            <section className="space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">{t('timeline.drawer.procedures')}</h3>
              {(contextBundle.l4_related_procedures || []).map((procedure, index) => (
                <div key={`${procedure.skill_id || index}`} className="rounded-xl border border-border/60 px-3 py-3 text-sm text-foreground">
                  {String(procedure.skill_name || '')}
                </div>
              ))}
            </section>
          </div>
        ) : null}
      </div>
    </aside>
  );
};

export default TimelineContextDrawer;
