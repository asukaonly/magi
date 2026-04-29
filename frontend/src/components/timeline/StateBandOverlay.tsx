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
const valencePct = (v: number | undefined): number => {
  if (typeof v !== 'number' || Number.isNaN(v)) return 50;
  return Math.round(((Math.max(-1, Math.min(1, v)) + 1) / 2) * 100);
};

/** Map valence (-1…1) to a muted HSL colour. */
const valenceColor = (v: number): string => {
  const hue = 200 - v * 180;
  const sat = 12 + Math.abs(v) * 38;
  const light = 52 - Math.abs(v) * 6;
  return `hsl(${Math.round(hue)} ${Math.round(sat)}% ${Math.round(light)}%)`;
};

const MetricBar: React.FC<{ percent: number; color: string }> = ({ percent, color }) => (
  <div className="h-1 w-full rounded-full bg-foreground/[0.06]">
    <div
      className="h-full rounded-full transition-all duration-500"
      style={{ width: `${Math.max(4, Math.min(100, percent))}%`, backgroundColor: color }}
    />
  </div>
);

const MetricCell: React.FC<{ label: string; percent: number; color: string; caption?: string }> = ({
  label,
  percent,
  color,
  caption,
}) => (
  <div className="space-y-1.5 rounded-lg border border-border/35 bg-card/70 px-3 py-2.5">
    <div className="flex items-baseline justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums text-foreground">{percent}%</span>
    </div>
    <MetricBar percent={percent} color={color} />
    {caption ? <div className="truncate text-[11px] text-muted-foreground/70">{caption}</div> : null}
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
      label: bands
        .map((band) => band.label)
        .find((label) => typeof label === 'string' && label.trim().length > 0),
    };
  }, [bands]);

  const visibleMarkers = markers.slice(0, 3);
  const stripBands = bands.slice(0, 36);

  if (bands.length === 0 && markers.length === 0) return null;

  return (
    <section className="space-y-4">
      {summary && (
        <div className="grid grid-cols-3 gap-3">
          <MetricCell
            label={t('timeline.metrics.valence')}
            percent={valencePct(summary.valence)}
            color="hsl(var(--primary) / 0.65)"
            caption={summary.label}
          />
          <MetricCell
            label={t('timeline.metrics.stress')}
            percent={pct(summary.stress)}
            color="hsl(0 50% 58%)"
          />
          <MetricCell
            label={t('timeline.metrics.engagement')}
            percent={pct(summary.engagement)}
            color="hsl(152 40% 46%)"
          />
        </div>
      )}

      {bands.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex h-2 overflow-hidden rounded-full bg-foreground/[0.05]">
            {stripBands.map((band) => (
              <div
                key={band.band_id}
                className="min-w-[3px] flex-1"
                title={`${band.label} · ${t('timeline.metrics.stress')} ${pct(band.stress_level)}%`}
                style={{
                  backgroundColor: valenceColor(band.valence),
                  opacity: 0.42 + clamp01(band.confidence) * 0.45,
                }}
              />
            ))}
          </div>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground/60">
            <span>{t('timeline.stateSummary.periods', { count: bands.length })}</span>
            {bands.length > stripBands.length ? <span>{t('timeline.stateSummary.sampled')}</span> : null}
          </div>
        </div>
      )}

      {visibleMarkers.length > 0 && (
        <div className="flex flex-col gap-2 border-l-2 border-primary/20 pl-4">
          {visibleMarkers.map((marker) => (
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
