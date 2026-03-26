import React from 'react';

import type { TimelineStateBand, TimelineStateMarker } from '@/api/modules/timeline';

interface StateBandOverlayProps {
  bands: TimelineStateBand[];
  markers: TimelineStateMarker[];
  scale: 'month' | 'week' | 'day' | 'hour';
}

const clampPercent = (value: number | undefined): number => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value * 100)));
};

const scaleLabelMap: Record<StateBandOverlayProps['scale'], string> = {
  month: 'Monthly climate',
  week: 'Weekly rhythm',
  day: 'Daily arc',
  hour: 'Hourly pulse',
};

export const StateBandOverlay: React.FC<StateBandOverlayProps> = ({ bands, markers, scale }) => {
  if (bands.length === 0 && markers.length === 0) {
    return null;
  }

  const primaryBand = bands[0];
  const bandGradient = bands.length > 0
    ? `linear-gradient(90deg, rgba(14,116,144,0.18) 0%, rgba(190,24,93,0.16) ${Math.max(
        24,
        clampPercent(primaryBand?.stress_level)
      )}%, rgba(202,138,4,0.2) 100%)`
    : undefined;

  return (
    <section
      className="overflow-hidden rounded-[28px] border border-border/60 bg-[radial-gradient(circle_at_top_left,rgba(190,24,93,0.08),transparent_34%),radial-gradient(circle_at_top_right,rgba(14,116,144,0.12),transparent_30%),linear-gradient(180deg,rgba(15,23,42,0.02),rgba(15,23,42,0.08))] p-5"
      style={bandGradient ? { backgroundImage: `${bandGradient}, radial-gradient(circle at top left, rgba(190,24,93,0.08), transparent 34%), radial-gradient(circle at top right, rgba(14,116,144,0.12), transparent 30%), linear-gradient(180deg, rgba(15,23,42,0.02), rgba(15,23,42,0.08))` } : undefined}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">{scaleLabelMap[scale]}</div>
          <div className="flex flex-wrap items-center gap-2">
            {primaryBand?.label ? (
              <span className="rounded-full border border-white/40 bg-white/60 px-3 py-1 text-xs font-medium text-foreground shadow-sm backdrop-blur">
                {primaryBand.label}
              </span>
            ) : null}
            <span className="rounded-full bg-foreground/[0.04] px-3 py-1 text-xs text-muted-foreground">{bands.length} bands</span>
            <span className="rounded-full bg-foreground/[0.04] px-3 py-1 text-xs text-muted-foreground">{markers.length} markers</span>
          </div>
        </div>

        <div className="grid min-w-[220px] flex-1 gap-2 sm:grid-cols-3">
          <div className="rounded-2xl bg-white/60 px-3 py-3 backdrop-blur">
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Valence</div>
            <div className="mt-2 text-lg font-semibold text-foreground">{clampPercent(primaryBand?.valence)}%</div>
          </div>
          <div className="rounded-2xl bg-white/60 px-3 py-3 backdrop-blur">
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Stress</div>
            <div className="mt-2 text-lg font-semibold text-foreground">{clampPercent(primaryBand?.stress_level)}%</div>
          </div>
          <div className="rounded-2xl bg-white/60 px-3 py-3 backdrop-blur">
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Engagement</div>
            <div className="mt-2 text-lg font-semibold text-foreground">{clampPercent(primaryBand?.engagement)}%</div>
          </div>
        </div>
      </div>

      {bands.length > 0 ? (
        <div className="mt-5 grid gap-2">
          {bands.map((band) => (
            <div key={band.band_id} className="grid grid-cols-[120px_minmax(0,1fr)] items-center gap-3">
              <div className="text-xs font-medium text-muted-foreground">{band.label}</div>
              <div className="relative h-3 overflow-hidden rounded-full bg-black/5">
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-[linear-gradient(90deg,rgba(14,116,144,0.7),rgba(217,119,6,0.72),rgba(190,24,93,0.7))]"
                  style={{ width: `${Math.max(18, clampPercent(band.engagement || band.valence))}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {markers.length > 0 ? (
        <div className="mt-5 flex flex-wrap gap-3">
          {markers.map((marker) => (
            <div
              key={marker.marker_id}
              className="max-w-xl rounded-2xl border border-white/50 bg-white/70 px-4 py-3 text-sm text-muted-foreground shadow-sm backdrop-blur"
            >
              <div className="text-[11px] uppercase tracking-[0.14em] text-foreground/70">{marker.label}</div>
              <div className="mt-1">{marker.summary}</div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
};

export default StateBandOverlay;
