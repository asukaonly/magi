import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineStateBand, TimelineStateChange, TimelineStateSummary } from '@/api/modules/timeline';

interface StateBandOverlayProps {
  bands: TimelineStateBand[];
  stateSummary: TimelineStateSummary;
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

const isNumber = (value: number | null | undefined): value is number =>
  typeof value === 'number' && !Number.isNaN(value);

const changeKey = (change: TimelineStateChange, index: number): string => {
  const anchor = change.anchor;
  if (anchor && typeof anchor.anchor_id === 'string' && anchor.anchor_id) {
    return anchor.anchor_id;
  }
  return `${change.label}-${index}`;
};

export const StateBandOverlay: React.FC<StateBandOverlayProps> = ({ bands, stateSummary, scale: _scale }) => {
  const { t } = useTranslation('app');

  const summary = useMemo(() => {
    const hasValues = isNumber(stateSummary.mood_value)
      || isNumber(stateSummary.stress_value)
      || isNumber(stateSummary.engagement_value);
    if (!hasValues) return null;
    return {
      valence: stateSummary.mood_value ?? undefined,
      stress: stateSummary.stress_value ?? undefined,
      engagement: stateSummary.engagement_value ?? undefined,
      label: stateSummary.mood_label,
      stressLabel: stateSummary.stress_label,
      engagementLabel: stateSummary.engagement_label,
    };
  }, [stateSummary]);

  const visibleChanges = stateSummary.notable_changes.slice(0, 3);
  const stripBands = bands.slice(0, 36);

  if (bands.length === 0 && visibleChanges.length === 0 && !summary) return null;

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
            caption={summary.stressLabel}
          />
          <MetricCell
            label={t('timeline.metrics.engagement')}
            percent={pct(summary.engagement)}
            color="hsl(152 40% 46%)"
            caption={summary.engagementLabel}
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

      {visibleChanges.length > 0 && (
        <div className="flex flex-col gap-2 border-l-2 border-primary/20 pl-4">
          {visibleChanges.map((change, index) => (
            <div key={changeKey(change, index)} className="text-sm">
              <span className="font-medium text-foreground">{change.label}</span>
              <span className="mx-1.5 text-muted-foreground/40">·</span>
              <span className="text-muted-foreground">{change.summary}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

export default StateBandOverlay;
