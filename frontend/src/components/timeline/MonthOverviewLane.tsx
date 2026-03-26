import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineReflectionWindow, TimelineStateBand } from '@/api/modules/timeline';

interface MonthOverviewLaneProps {
  reflections: TimelineReflectionWindow[];
  stateBands: TimelineStateBand[];
}

export const MonthOverviewLane: React.FC<MonthOverviewLaneProps> = ({ reflections, stateBands }) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-4">
      {reflections.map((reflection) => (
        <article key={reflection.reflection_id} className="rounded-2xl border border-border/60 bg-card/70 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-foreground">{reflection.title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{reflection.summary}</p>
            </div>
            <div className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
              {stateBands[0]?.label || t('timeline.labels.selfState')}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
};

export default MonthOverviewLane;
