import React from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import type { TimelineSourceMixItem, TimelineThemeCard } from '@/api/modules/timeline';

interface MonthOverviewLaneProps {
  sourceMix: TimelineSourceMixItem[];
  themeCards: TimelineThemeCard[];
  onOpenContext: (anchorId: string) => void;
}

const MODE_COLORS: Record<string, string> = {
  chrome_history: 'hsl(210 55% 58%)',
  chat: 'hsl(280 45% 58%)',
  git_activity: 'hsl(150 45% 45%)',
  terminal_history: 'hsl(35 60% 50%)',
  screen_time: 'hsl(340 50% 55%)',
  calendar: 'hsl(190 50% 48%)',
  photo_library: 'hsl(25 65% 55%)',
  netease_music: 'hsl(0 60% 58%)',
  manual_journal: 'hsl(45 55% 50%)',
};

const modeColor = (mode: string): string =>
  MODE_COLORS[mode] || `hsl(${(mode.charCodeAt(0) * 37) % 360} 35% 55%)`;

const formatDuration = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

const buildModeDistribution = (sourceMix: TimelineSourceMixItem[]) =>
  sourceMix
    .map((item) => ({
      mode: item.source_type,
      label: item.label,
      seconds: Math.max(0, item.duration_seconds || 0),
      count: Math.max(0, item.event_count || 0),
    }))
    .sort((a, b) => b.count - a.count || b.seconds - a.seconds || a.mode.localeCompare(b.mode));

const resolveSourceLabel = (
  mode: string,
  label: string | undefined,
  t: TFunction<'app'>,
): string => {
  const normalized = String(label || '').trim();
  return normalized || t(`timeline.sources.${mode}`, mode);
};

const ThemeCardContent: React.FC<{ card: TimelineThemeCard }> = ({ card }) => {
  const { t } = useTranslation('app');

  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="min-w-0 truncate text-sm font-semibold text-foreground">{card.title}</h2>
        <span className="shrink-0 text-[11px] text-muted-foreground/60">
          {t('timeline.cluster.groupSummary', { count: card.event_count })}
        </span>
      </div>
      {card.summary ? (
        <p className="mt-1.5 line-clamp-3 text-sm leading-relaxed text-muted-foreground">
          {card.summary}
        </p>
      ) : null}
      {card.source_types.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {card.source_types.slice(0, 4).map((source) => (
            <span
              key={source}
              className="rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground"
            >
              {t(`timeline.sources.${source}`, source)}
            </span>
          ))}
        </div>
      )}
    </>
  );
};

const ThemeCardItem: React.FC<{
  card: TimelineThemeCard;
  onOpenContext: (anchorId: string) => void;
}> = ({ card, onOpenContext }) => {
  const anchorId = card.anchor.anchor_id;
  if (anchorId) {
    return (
      <button
        type="button"
        className="rounded-lg border border-border/40 bg-card px-4 py-3 text-left transition-colors hover:border-border hover:bg-muted/30 focus:outline-none focus:ring-1 focus:ring-ring/30"
        onClick={() => onOpenContext(anchorId)}
      >
        <ThemeCardContent card={card} />
      </button>
    );
  }

  return (
    <article className="rounded-lg border border-border/40 bg-card px-4 py-3">
      <ThemeCardContent card={card} />
    </article>
  );
};

export const MonthOverviewLane: React.FC<MonthOverviewLaneProps> = ({
  sourceMix,
  themeCards,
  onOpenContext,
}) => {
  const { t } = useTranslation('app');
  const distribution = buildModeDistribution(sourceMix);
  const totalSeconds = distribution.reduce((s, d) => s + d.seconds, 0);
  const totalCount = distribution.reduce((s, d) => s + d.count, 0);

  return (
    <div className="space-y-6">
      {distribution.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('timeline.activity.distribution')}
          </h3>
          <div className="flex h-2.5 overflow-hidden rounded-sm">
            {distribution.map(({ mode, label, seconds, count }) => (
              <div
                key={mode}
                className="transition-all duration-500 first:rounded-l-sm last:rounded-r-sm"
                style={{
                  width: `${((totalSeconds > 0 ? seconds : count) / (totalSeconds > 0 ? totalSeconds : totalCount)) * 100}%`,
                  backgroundColor: modeColor(mode),
                  opacity: 0.75,
                }}
                title={`${resolveSourceLabel(mode, label, t)} · ${seconds > 0 ? formatDuration(seconds) : `${count} ${t('timeline.summary.totalEvents')}`}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {distribution.map(({ mode, label, seconds, count }) => (
              <div key={mode} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className="inline-block h-2 w-2 rounded-[2px]"
                  style={{ backgroundColor: modeColor(mode) }}
                />
                <span>{resolveSourceLabel(mode, label, t)}</span>
                <span className="tabular-nums text-muted-foreground/60">
                  {seconds > 0 ? formatDuration(seconds) : `${count} ${t('timeline.summary.totalEvents')}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {themeCards.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('timeline.month.themes')}
          </h3>
          <div className="grid gap-3 lg:grid-cols-2">
            {themeCards.map((card) => (
              <ThemeCardItem key={card.theme_id} card={card} onOpenContext={onOpenContext} />
            ))}
          </div>
        </section>
      )}

      {distribution.length === 0 && themeCards.length === 0 && (
        <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
          {t('timeline.empty.window')}
        </div>
      )}
    </div>
  );
};

export default MonthOverviewLane;
