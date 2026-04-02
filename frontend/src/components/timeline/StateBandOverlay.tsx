import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineStateBand, TimelineStateMarker } from '@/api/modules/timeline';

interface StateBandOverlayProps {
  bands: TimelineStateBand[];
  markers: TimelineStateMarker[];
  scale: 'month' | 'week' | 'day' | 'hour';
}

const clamp01 = (v: number | undefined): number => {
  if (typeof v !== 'number' || Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(1, v));
};

const pct = (v: number | undefined): number => Math.round(clamp01(v) * 100);

/** Map valence (-1…1) to a muted HSL colour. */
const valenceColor = (v: number): string => {
  const hue = 200 - v * 180;
  const sat = 12 + Math.abs(v) * 38;
  const light = 52 - Math.abs(v) * 6;
  return `hsl(${Math.round(hue)} ${Math.round(sat)}% ${Math.round(light)}%)`;
};

/** Tiny inline bar for a 0-1 metric. */
const MetricBar: React.FC<{ value: number; color: string }> = ({ value, color }) => (
  <div className="h-1 w-full rounded-full bg-foreground/[0.06]">
    <div
      className="h-full rounded-full transition-all duration-500"
      style={{ width: `${Math.max(4, pct(value))}%`, backgroundColor: color }}
    />
  </div>
);

const MetricCell: React.FC<{ label: string; value: number; color: string }> = ({
  label,
  value,
  color,
}) => (
  <div className="space-y-1.5">
    <div className="flex items-baseline justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums text-foreground">{pct(value)}%</span>
    </div>
    <MetricBar value={value} color={color} />
  </div>
);

export const StateBandOverlay: React.FC<StateBandOverlayProps> = ({ bands, markers, scale: _scale }) => {
  const { t } = useTranslation('app');

  const summary = useMemo(() => {
    if (bands.length === 0) return null;
    const avg = (fn: (b: TimelineStateBand) => number) =>
      bands.reduce((s, b) => s + fn(b), 0) / bands.length;
    return {
      valence: avg((b) => b.valence),
      stress: avg((b) => b.stress_level),
      engagement: avg((b) => b.engagement),
    };
  }, [bands]);

  if (bands.length === 0 && markers.length === 0) return null;

  return (
    <section className="space-y-4">
      {/* Metric summary */}
      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <MetricCell
            label={t('timeline.metrics.valence')}
            value={summary.valence}
            color="hsl(var(--primary) / 0.65)"
          />
          <MetricCell
            label={t('timeline.metrics.stress')}
            value={summary.stress}
            color="hsl(0 50% 58%)"
          />
          <MetricCell
            label={t('timeline.metrics.engagement')}
            value={summary.engagement}
            color="hsl(152 40% 46%)"
          />
        </div>
      )}

      {/* Band strip visualization */}
      {bands.length > 0 && (
        <div className="space-y-1.5">
          {bands.map((band) => (
            <div key={band.band_id} className="group flex items-center gap-3">
              <span className="w-20 shrink-0 truncate text-xs text-muted-foreground">
                {band.label}
              </span>
              <div className="relative flex h-2 flex-1 items-center rounded-sm bg-foreground/[0.04]">
                <div
                  className="absolute inset-y-0 left-0 rounded-sm transition-all duration-500"
                  style={{
                    width: `${Math.max(2, pct(band.engagement || band.valence))}%`,
                    backgroundColor: valenceColor(band.valence),
                    opacity: 0.5 + clamp01(band.confidence) * 0.4,
                  }}
                />
                {band.stress_level > 0.6 && (
                  <div
                    className="absolute top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-red-400/60"
                    style={{ left: `${pct(band.stress_level)}%` }}
                  />
                )}
              </div>
              <span className="w-8 text-right text-[11px] tabular-nums text-muted-foreground/60">
                {pct(band.engagement)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* State shift markers */}
      {markers.length > 0 && (
        <div className="flex flex-col gap-2 border-l-2 border-primary/20 pl-4">
          {markers.map((marker) => (
            <div key={marker.marker_id} className="text-sm">
              <span className="font-medium text-foreground">{marker.label}</span>
              <span className="mx-1.5 text-muted-foreground/40">·</span>
              <span className="text-muted-foreground">{marker.summary}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

export default StateBandOverlay;
