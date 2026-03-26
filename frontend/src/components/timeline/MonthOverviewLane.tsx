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
        <article
          key={reflection.reflection_id}
          className="overflow-hidden rounded-[28px] border border-border/60 bg-[linear-gradient(135deg,rgba(255,255,255,0.92),rgba(248,250,252,0.82))] p-6 shadow-[0_18px_60px_-36px_rgba(15,23,42,0.45)]"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-3">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Reflection window</div>
              <h2 className="text-xl font-semibold tracking-tight text-foreground">{reflection.title}</h2>
              <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{reflection.summary}</p>
            </div>
            <div className="rounded-full border border-border/60 bg-white/80 px-3 py-1 text-xs text-muted-foreground">
              {stateBands[0]?.label || t('timeline.labels.selfState')}
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            {reflection.key_topics.map((topic) => (
              <span key={topic} className="rounded-full bg-sky-100/80 px-3 py-1 text-xs font-medium text-sky-900">
                {topic}
              </span>
            ))}
          </div>

          {reflection.change_and_pattern ? (
            <div className="mt-5 rounded-2xl border border-border/60 bg-foreground/[0.03] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Pattern signal</div>
              <div className="mt-2 text-sm text-foreground">
                {JSON.stringify(reflection.change_and_pattern)}
              </div>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
};

export default MonthOverviewLane;
