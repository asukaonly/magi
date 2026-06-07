import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface WeekListPickerProps {
  /** Unix seconds at the start of the currently-selected week (Monday 00:00 local). */
  selectedWeekStart: number;
  /** Fired with "YYYY-Www" ISO week string when the user picks a row. */
  onSelectWeek: (week: string) => void;
}

/** Monday-anchored start of the week containing `date`, normalized to 00:00 local. */
function startOfISOWeek(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  // JS: Sun=0..Sat=6 → ISO: Mon=0..Sun=6
  const dayNum = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - dayNum);
  return d;
}

/**
 * Compute the ISO-8601 week number for a date. Uses the Thursday rule so the
 * year matches the ISO calendar (e.g. Dec 31 may belong to week 1 of the next
 * year). All math done in UTC to dodge DST drift.
 */
function getISOWeek(date: Date): { year: number; week: number } {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = (d.getUTCDay() + 6) % 7;
  // Move to Thursday of this week
  d.setUTCDate(d.getUTCDate() - dayNum + 3);
  // Thursday of ISO week 1 is the Thursday in the same week as Jan 4
  const week1Thursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const week1DayNum = (week1Thursday.getUTCDay() + 6) % 7;
  week1Thursday.setUTCDate(week1Thursday.getUTCDate() - week1DayNum + 3);
  const week = 1 + Math.round((d.getTime() - week1Thursday.getTime()) / (7 * 86_400_000));
  return { year: d.getUTCFullYear(), week };
}

/** Locale-aware Monday→Sunday range label, e.g. "May 11 – May 17" / "5月11日 – 5月17日". */
function formatWeekRange(start: Date, end: Date, locale: string): string {
  const fmt = (d: Date) => d.toLocaleDateString(locale, { month: "short", day: "numeric" });
  return `${fmt(start)} – ${fmt(end)}`;
}

/** All week-start (Monday) Dates that overlap with the given month. */
function weeksOverlappingMonth(year: number, month: number): Date[] {
  const firstOfMonth = new Date(year, month - 1, 1);
  const lastOfMonth = new Date(year, month, 0);
  const firstWeekStart = startOfISOWeek(firstOfMonth);
  const weeks: Date[] = [];
  const cursor = new Date(firstWeekStart);
  while (cursor <= lastOfMonth) {
    weeks.push(new Date(cursor));
    cursor.setDate(cursor.getDate() + 7);
  }
  return weeks;
}

/**
 * Picker tuned for `scale === "week"`. Renders the weeks overlapping the
 * currently-viewed month as a list of rows, each showing the Monday→Sunday
 * date range. Today's week gets a dot; the selected week gets a filled row.
 * Month navigation is via the prev/next chevrons in the header.
 *
 * Sized to match the day Calendar so swapping pickers doesn't reflow the
 * popover container.
 */
export const WeekListPicker: React.FC<WeekListPickerProps> = ({
  selectedWeekStart,
  onSelectWeek,
}) => {
  const { i18n } = useTranslation();
  const selectedStart = startOfISOWeek(new Date(selectedWeekStart * 1000));
  const [viewYear, setViewYear] = useState<number>(selectedStart.getFullYear());
  const [viewMonth, setViewMonth] = useState<number>(selectedStart.getMonth() + 1);

  const goPrev = () => {
    if (viewMonth === 1) {
      setViewYear((y) => y - 1);
      setViewMonth(12);
    } else {
      setViewMonth((m) => m - 1);
    }
  };
  const goNext = () => {
    if (viewMonth === 12) {
      setViewYear((y) => y + 1);
      setViewMonth(1);
    } else {
      setViewMonth((m) => m + 1);
    }
  };

  const weeks = weeksOverlappingMonth(viewYear, viewMonth);

  const todayWeekStart = startOfISOWeek(new Date()).getTime();
  const selectedTime = selectedStart.getTime();

  return (
    <div className="w-[240px] p-3">
      {/* Month header */}
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={goPrev}
          onMouseDown={(e) => e.stopPropagation()}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/5"
          aria-label="prev month"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <div className="text-sm font-medium">
          {new Date(viewYear, viewMonth - 1, 1).toLocaleDateString(i18n.language, {
            year: "numeric",
            month: "long",
          })}
        </div>
        <button
          type="button"
          onClick={goNext}
          onMouseDown={(e) => e.stopPropagation()}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/5"
          aria-label="next month"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Week rows */}
      <div className="flex flex-col gap-0.5">
        {weeks.map((weekStart) => {
          const weekEnd = new Date(weekStart);
          weekEnd.setDate(weekEnd.getDate() + 6);
          const isSelected = weekStart.getTime() === selectedTime;
          const isCurrentWeek = weekStart.getTime() === todayWeekStart;
          const { year, week } = getISOWeek(weekStart);
          const value = `${year}-W${String(week).padStart(2, "0")}`;

          return (
            <button
              key={weekStart.toISOString()}
              type="button"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => onSelectWeek(value)}
              className={cn(
                "relative flex items-center justify-between rounded-md px-3 py-2 text-sm transition-colors",
                isSelected
                  ? "bg-primary text-primary-foreground"
                  : "text-foreground hover:bg-foreground/5",
              )}
            >
              <span>{formatWeekRange(weekStart, weekEnd, i18n.language)}</span>
              {isCurrentWeek && !isSelected && (
                <span
                  className="h-1 w-1 rounded-full bg-foreground/80"
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
