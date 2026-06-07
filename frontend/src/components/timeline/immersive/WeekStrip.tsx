import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineClusterBlock } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";
import {
  formatDurationCompact,
  groupClustersIntoWeekDays,
  type DayRollup,
} from "@/lib/timeline-buckets";

import { SourceIcon } from "./SourceIcon";

interface WeekStripProps {
  clusters: TimelineClusterBlock[];
  /** Unix seconds at Monday 00:00 of the displayed week. */
  weekStart: number;
  /** Fired when user clicks a day card. Receives ISO date "YYYY-MM-DD". */
  onSelectDay: (isoDate: string) => void;
}

/**
 * Week-scale main content: 7 horizontal day cards. Each card surfaces a
 * compact "what kind of day was this" — total duration + top 3 source
 * icons. Click a card to drill into that day's scale-day view.
 *
 * Empty days still render (greyed) so the calendar shape is legible — a
 * week with only 3 active days reads as "3 active, 4 quiet" rather than a
 * cramped 3-card row that hides the rhythm.
 */
export const WeekStrip: React.FC<WeekStripProps> = ({
  clusters,
  weekStart,
  onSelectDay,
}) => {
  const days = groupClustersIntoWeekDays(clusters, weekStart);
  const todayIso = (() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  })();

  return (
    <div className="grid grid-cols-7 gap-2 px-6 pb-10 pt-3">
      {days.map((day) => (
        <DayCard
          key={day.isoDate}
          day={day}
          isToday={day.isoDate === todayIso}
          onSelect={() => onSelectDay(day.isoDate)}
        />
      ))}
    </div>
  );
};

const DayCard: React.FC<{
  day: DayRollup;
  isToday: boolean;
  onSelect: () => void;
}> = ({ day, isToday, onSelect }) => {
  const { i18n } = useTranslation();
  const hasActivity = day.items.length > 0;
  const dateNumber = new Date(day.dayStart * 1000).getDate();

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group relative flex min-h-[140px] flex-col rounded-lg border p-3 text-left transition-colors",
        hasActivity
          ? "border-border bg-background/60 hover:bg-foreground/[0.03]"
          : "border-dashed border-border/50 bg-transparent text-muted-foreground/50 hover:bg-foreground/[0.02]",
      )}
    >
      <div className="mb-2 flex items-baseline justify-between">
        <span
          className={cn(
            "text-[11px] uppercase tracking-[0.15em]",
            isToday ? "font-semibold text-foreground" : "text-muted-foreground",
          )}
        >
          {new Date(day.dayStart * 1000).toLocaleDateString(i18n.language, { weekday: "short" })}
        </span>
        <span
          className={cn(
            "font-mono text-[18px]",
            isToday ? "font-medium text-foreground" : "text-muted-foreground/80",
          )}
        >
          {dateNumber}
        </span>
      </div>

      {hasActivity ? (
        <>
          <div className="mb-2 flex items-center gap-1.5">
            {day.topSources.map(({ sourceType, durationSeconds }) => (
              <span
                key={sourceType}
                className="flex items-center gap-1 rounded bg-foreground/[0.04] px-1.5 py-0.5"
                title={`${sourceType} · ${formatDurationCompact(durationSeconds)}`}
              >
                <SourceIcon sourceType={sourceType} className="h-3 w-3" />
                <span className="font-mono text-[10px] text-muted-foreground">
                  {formatDurationCompact(durationSeconds)}
                </span>
              </span>
            ))}
          </div>
          <div className="mt-auto font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/60">
            {formatDurationCompact(day.totalDurationSeconds)}
          </div>
        </>
      ) : (
        <div className="mt-auto text-[10px] text-muted-foreground/50">
          ·
        </div>
      )}
    </button>
  );
};
