import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineMoodCalendarDay } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";

interface MoodCalendarProps {
  month: string;  // "YYYY-MM"
  days: TimelineMoodCalendarDay[];
  selectedDate: string;
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

export const MoodCalendar: React.FC<MoodCalendarProps> = ({
  month,
  days,
  selectedDate,
  onSelectDate,
}) => {
  const { t } = useTranslation("app");

  const [year, monthNum] = month.split("-").map(Number);
  const firstOfMonth = new Date(year, monthNum - 1, 1);
  const daysInMonth = new Date(year, monthNum, 0).getDate();
  // Monday-start week — pad leading empties
  const leadingPad = (firstOfMonth.getDay() + 6) % 7;

  const byDate = useMemo(() => {
    const m = new Map<string, TimelineMoodCalendarDay>();
    for (const d of days) m.set(d.date, d);
    return m;
  }, [days]);

  const weekdayHeaders = ["一", "二", "三", "四", "五", "六", "日"];

  const cells: React.ReactNode[] = [];
  for (let i = 0; i < leadingPad; i++) {
    cells.push(<div key={`pad-${i}`} aria-hidden="true" />);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const date = isoDate(year, monthNum, day);
    const moodDay = byDate.get(date);
    const isSelected = date === selectedDate;
    const isToday = (() => {
      const now = new Date();
      return now.getFullYear() === year && now.getMonth() === monthNum - 1 && now.getDate() === day;
    })();

    cells.push(
      <button
        key={date}
        type="button"
        aria-label={date}
        data-selected={isSelected ? "true" : "false"}
        onClick={() => onSelectDate(date)}
        className={cn(
          "relative aspect-square rounded-sm bg-[rgba(184,177,165,0.15)]",
          isSelected && "ring-1 ring-foreground"
        )}
      >
        {moodDay && (
          <span
            className={cn(
              "absolute inset-[2px] rounded-[2px] opacity-85",
              VALENCE_BG[moodDay.dominant_valence] ?? VALENCE_BG.neutral
            )}
            aria-hidden="true"
          />
        )}
        {isToday && (
          <span className="absolute inset-0 rounded-sm ring-[1.5px] ring-foreground/80 ring-inset" />
        )}
      </button>
    );
  }

  return (
    <div className="px-4 py-4">
      <div className="mb-2.5 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {t("timeline.immersive.moodCalendarLabel", { defaultValue: "这个月" })}
      </div>
      <div role="row" className="mb-1.5 grid grid-cols-7 gap-1 text-[9px] text-muted-foreground/80">
        {weekdayHeaders.map((label) => (
          <span key={label} role="columnheader" className="text-center">
            {label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">{cells}</div>
    </div>
  );
};
