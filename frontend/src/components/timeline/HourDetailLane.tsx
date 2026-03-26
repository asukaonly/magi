import React from 'react';
import { Clock3 } from 'lucide-react';

import type { TimelineRawEvent } from '@/api/modules/timeline';

interface HourDetailLaneProps {
  rawEvents: TimelineRawEvent[];
}

export const HourDetailLane: React.FC<HourDetailLaneProps> = ({ rawEvents }) => (
  <div className="space-y-4">
    {rawEvents.map((event) => (
      <article key={event.event_id} className="rounded-2xl border border-border/60 bg-card/70 p-5">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />
          {event.source_type}
        </div>
        <h2 className="mt-2 text-lg font-semibold text-foreground">{event.title}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{event.summary}</p>
      </article>
    ))}
  </div>
);

export default HourDetailLane;
