import React from 'react';
import { Clock3 } from 'lucide-react';

import type { TimelineRawEvent } from '@/api/modules/timeline';

interface HourDetailLaneProps {
  rawEvents: TimelineRawEvent[];
}

const formatTimestamp = (timestamp: number): string =>
  new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(timestamp * 1000));

export const HourDetailLane: React.FC<HourDetailLaneProps> = ({ rawEvents }) => (
  <div className="space-y-4">
    {rawEvents.map((event) => (
      <article
        key={event.event_id}
        className="relative overflow-hidden rounded-[24px] border border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.95),rgba(248,250,252,0.82))] p-5"
      >
        <div className="absolute left-0 top-5 h-16 w-1 rounded-r-full bg-[linear-gradient(180deg,rgba(14,116,144,0.8),rgba(190,24,93,0.8))]" />
        <div className="flex items-center gap-2 pl-3 text-xs text-muted-foreground">
          <Clock3 className="h-3.5 w-3.5" />
          {formatTimestamp(event.timestamp)}
          <span className="text-muted-foreground/60">•</span>
          {event.source_type}
        </div>
        <h2 className="mt-2 pl-3 text-lg font-semibold text-foreground">{event.title}</h2>
        <p className="mt-2 pl-3 text-sm leading-6 text-muted-foreground">{event.summary}</p>
      </article>
    ))}
  </div>
);

export default HourDetailLane;
