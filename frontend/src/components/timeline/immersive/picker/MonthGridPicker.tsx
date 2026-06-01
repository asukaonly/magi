import React, { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface MonthGridPickerProps {
  /** Currently selected month in "YYYY-MM" format. */
  selectedMonth: string;
  /** Fired with "YYYY-MM" when the user picks a month. */
  onSelectMonth: (month: string) => void;
}

/**
 * Picker tuned for `scale === "month"`: shows a 4×3 grid of months for a single
 * year. No days appear. Today's month gets a dot under its name; the selected
 * month gets a filled cell. Year navigation is via the prev/next chevrons in
 * the header.
 *
 * Designed to drop into a Popover slot the same size as the day Calendar so
 * switching scales doesn't reflow the popover.
 */
export const MonthGridPicker: React.FC<MonthGridPickerProps> = ({
  selectedMonth,
  onSelectMonth,
}) => {
  // Parse "YYYY-MM" defensively — fall back to the current year if malformed.
  const parsed = (() => {
    const [y, m] = selectedMonth.split("-").map(Number);
    if (!Number.isFinite(y) || !Number.isFinite(m)) {
      const now = new Date();
      return { year: now.getFullYear(), month: now.getMonth() + 1 };
    }
    return { year: y, month: m };
  })();

  const [viewYear, setViewYear] = useState<number>(parsed.year);
  const now = new Date();
  const todayYear = now.getFullYear();
  const todayMonth = now.getMonth() + 1;

  return (
    <div className="w-[240px] p-3">
      {/* Year header */}
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setViewYear((y) => y - 1)}
          onMouseDown={(e) => e.stopPropagation()}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/5"
          aria-label="prev year"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <div className="text-sm font-medium">{viewYear} 年</div>
        <button
          type="button"
          onClick={() => setViewYear((y) => y + 1)}
          onMouseDown={(e) => e.stopPropagation()}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-foreground/5"
          aria-label="next year"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* 4 rows × 3 cols of months */}
      <div className="grid grid-cols-3 gap-1">
        {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
          const isSelected = viewYear === parsed.year && m === parsed.month;
          const isToday = viewYear === todayYear && m === todayMonth;
          return (
            <button
              key={m}
              type="button"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => {
                const value = `${viewYear}-${String(m).padStart(2, "0")}`;
                onSelectMonth(value);
              }}
              className={cn(
                "relative rounded-md py-2 text-sm transition-colors",
                isSelected
                  ? "bg-primary text-primary-foreground"
                  : "text-foreground hover:bg-foreground/5",
              )}
            >
              {m} 月
              {isToday && !isSelected && (
                <span
                  className="absolute bottom-1 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-foreground/80"
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
