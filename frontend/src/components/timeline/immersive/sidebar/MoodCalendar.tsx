import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineMoodCalendarDay } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";

type Scale = "month" | "week" | "day" | "hour";

interface MoodCalendarProps {
  /** "YYYY-MM" — which month the calendar grid currently displays. */
  month: string;
  /** Mood data keyed by ISO date strings. Days without an entry get no color. */
  days: TimelineMoodCalendarDay[];
  /** Active scale — controls which cells get the selection highlight. */
  scale: Scale;
  /** ISO date of selection range start (inclusive). For day/hour this is the
   *  single selected day; for week it's the Monday; for month it's the 1st. */
  selectedRangeStart: string;
  /** ISO date of selection range end (inclusive). For day/hour same as start;
   *  for week it's the Sunday; for month it's the last day of month. */
  selectedRangeEnd: string;
  /** Fired when the user clicks a cell (including outside-month cells). */
  onSelectDate: (isoDate: string) => void;
}

const VALENCE_BG: Record<string, string> = {
  warm: "bg-[#c9a878]",
  bright: "bg-[#d4b886]",
  neutral: "bg-[#a8a08a]",
  cool: "bg-[#7a8898]",
  tense: "bg-[#b87a78]",
};

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Strictly compare ISO date strings (YYYY-MM-DD) lexicographically. */
function inRange(iso: string, startIso: string, endIso: string): boolean {
  return iso >= startIso && iso <= endIso;
}

/**
 * Sidebar mood calendar with scale-aware selection range.
 *
 *  day / hour: a single cell is highlighted.
 *  week:       the 7-day Monday→Sunday range is highlighted as a horizontal
 *              band (cross-month weeks: outside-month cells are still shown
 *              and join the highlight, so the band reads as a complete week).
 *  month:      every in-month cell is highlighted with a softer band.
 *
 * Outside-month days appear muted (no mood color) so the calendar shape is
 * legible and week ranges that cross month boundaries don't look truncated.
 */
export const MoodCalendar: React.FC<MoodCalendarProps> = ({
  month,
  days,
  scale,
  selectedRangeStart,
  selectedRangeEnd,
  onSelectDate,
}) => {
  const { i18n } = useTranslation();
  // Monday-first short weekday initials in the active locale (2024-01-01 is a Monday).
  const weekdayHeaders = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(i18n.language, { weekday: "narrow" });
    return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)));
  }, [i18n.language]);
  const [year, monthNum] = month.split("-").map(Number);
  const firstOfMonth = new Date(year, monthNum - 1, 1);
  const daysInMonth = new Date(year, monthNum, 0).getDate();
  // Monday-start week — pad both leading and trailing with outside-month days
  const leadingPad = (firstOfMonth.getDay() + 6) % 7;

  const byDate = useMemo(() => {
    const m = new Map<string, TimelineMoodCalendarDay>();
    for (const d of days) m.set(d.date, d);
    return m;
  }, [days]);

  const todayIso = (() => {
    const now = new Date();
    return isoDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  })();

  // Build the full 42-cell (6-row) grid: leading outside days + this month +
  // trailing outside days. Always exactly 6 rows so the strip height is stable.
  type Cell = {
    iso: string;
    dayNumber: number;
    inMonth: boolean;
  };
  const cells: Cell[] = [];

  // Leading pad — previous month's tail
  if (leadingPad > 0) {
    const prevMonthYear = monthNum === 1 ? year - 1 : year;
    const prevMonth = monthNum === 1 ? 12 : monthNum - 1;
    const prevMonthDays = new Date(prevMonthYear, prevMonth, 0).getDate();
    for (let i = leadingPad - 1; i >= 0; i--) {
      const dayNumber = prevMonthDays - i;
      cells.push({
        iso: isoDate(prevMonthYear, prevMonth, dayNumber),
        dayNumber,
        inMonth: false,
      });
    }
  }
  // This month
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ iso: isoDate(year, monthNum, day), dayNumber: day, inMonth: true });
  }
  // Trailing pad — next month's head, to fill to 42 cells
  const trailingPad = 42 - cells.length;
  const nextMonthYear = monthNum === 12 ? year + 1 : year;
  const nextMonth = monthNum === 12 ? 1 : monthNum + 1;
  for (let i = 1; i <= trailingPad; i++) {
    cells.push({
      iso: isoDate(nextMonthYear, nextMonth, i),
      dayNumber: i,
      inMonth: false,
    });
  }

  return (
    <div className="px-4 py-4">
      <div className="mb-2.5 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {new Date(year, monthNum - 1, 1).toLocaleDateString(i18n.language, {
          year: "numeric",
          month: "long",
        })}
      </div>
      <div role="row" className="mb-1.5 grid grid-cols-7 gap-1 text-[9px] text-muted-foreground/80">
        {weekdayHeaders.map((label, i) => (
          <span key={i} role="columnheader" className="text-center">
            {label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((cell) => {
          const moodDay = cell.inMonth ? byDate.get(cell.iso) : undefined;
          const isToday = cell.iso === todayIso;
          const isSelected = inRange(cell.iso, selectedRangeStart, selectedRangeEnd);

          return (
            <button
              key={cell.iso}
              type="button"
              aria-label={cell.iso}
              aria-pressed={isSelected ? "true" : "false"}
              data-selected={isSelected ? "true" : "false"}
              data-in-month={cell.inMonth ? "true" : "false"}
              onClick={() => onSelectDate(cell.iso)}
              className={cn(
                "relative flex aspect-square items-center justify-center rounded-sm text-[10px] font-medium",
                // Mood color only for in-month cells with data
                moodDay
                  ? cn("text-white opacity-90", VALENCE_BG[moodDay.dominant_valence] ?? VALENCE_BG.neutral)
                  : cell.inMonth
                    ? "bg-transparent text-muted-foreground/70 hover:bg-foreground/5"
                    : "bg-transparent text-muted-foreground/30 hover:bg-foreground/[0.03]",
                // Selection styling differs by scale: day/hour uses a single
                // ring; week/month uses a soft band so a 7-cell range reads
                // as a continuous strip rather than a row of individual rings.
                isSelected && scale === "day" && "ring-1 ring-foreground",
                isSelected && scale === "hour" && "ring-1 ring-foreground",
                isSelected && (scale === "week" || scale === "month") && "bg-foreground/10",
              )}
            >
              <span className="relative z-10">{cell.dayNumber}</span>
              {isToday && (
                <span
                  className="absolute bottom-0.5 left-1/2 z-10 h-1 w-1 -translate-x-1/2 rounded-full bg-foreground/80"
                  aria-hidden="true"
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};
