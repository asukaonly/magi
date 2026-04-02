import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineRawEvent } from '@/api/modules/timeline';

interface HourDetailLaneProps {
  rawEvents: TimelineRawEvent[];
}

const formatTimestamp = (ts: number): string =>
  new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(ts * 1000));

export const HourDetailLane: React.FC<HourDetailLaneProps> = ({ rawEvents }) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-0.5">
      {rawEvents.map((event) => (
        <div
          key={event.event_id}
          className="group flex gap-4 rounded-lg px-3 py-2.5 transition-colors hover:bg-muted/40"
        >
          <span className="w-12 shrink-0 pt-0.5 text-right text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(event.timestamp)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-medium text-foreground">{event.title}</span>
              <span className="shrink-0 text-[11px] text-muted-foreground/50">
                {t(`timeline.sources.${event.source_type}`, event.source_type)}
              </span>
            </div>
            {event.summary && (
              <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">{event.summary}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

export default HourDetailLane;
