import React from 'react';

import type { TimelineStateBand, TimelineStateMarker } from '@/api/modules/timeline';

interface StateBandOverlayProps {
  bands: TimelineStateBand[];
  markers: TimelineStateMarker[];
  scale: 'month' | 'week' | 'day' | 'hour';
}

export const StateBandOverlay: React.FC<StateBandOverlayProps> = ({ bands, markers, scale }) => {
  if (bands.length === 0 && markers.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
        <span>{scale}</span>
        {bands[0]?.label ? <span>{bands[0].label}</span> : null}
      </div>
      {markers.map((marker) => (
        <div key={marker.marker_id} className="rounded-xl border border-dashed border-border/60 px-4 py-3 text-sm text-muted-foreground">
          {marker.summary}
        </div>
      ))}
    </div>
  );
};

export default StateBandOverlay;
