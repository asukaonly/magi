import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineViewportResponse } from "@/api/modules/timeline";

interface HourDetailProps {
  viewport: TimelineViewportResponse;
}

function formatHourMinute(sec: number): string {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * Hour scale = "侦探模式": raw L1 events shown as a chronological evidence
 * list. The backend deliberately ships clusters=[] at hour scale so we don't
 * cluster too aggressively at minute granularity — the value of the hour view
 * is seeing every artifact.
 *
 * Falls back to rendering clusters when raw_events is empty (defensive — some
 * historical viewport responses may still carry them).
 */
export const HourDetail: React.FC<HourDetailProps> = ({ viewport }) => {
  const { t } = useTranslation("app");
  const clusters = viewport.clusters ?? [];
  const rawEvents = viewport.raw_events ?? [];

  if (clusters.length === 0 && rawEvents.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
        {t("timeline.immersive.hourEmpty", { defaultValue: "这个小时没什么动静。" })}
      </div>
    );
  }

  // Prefer raw events when present (the designed-for path); cluster fallback
  // remains for old payloads.
  if (rawEvents.length > 0) {
    return (
      <div className="divide-y divide-border/30 px-10 py-5">
        {rawEvents.map((ev) => (
          <div
            key={ev.event_id}
            className="grid grid-cols-[110px_1fr] gap-7 py-3"
          >
            <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
              {formatHourMinute(ev.timestamp)}
            </div>
            <div>
              <div className="text-sm text-foreground">{ev.title}</div>
              {ev.summary && ev.summary !== ev.title && (
                <div className="mt-1 text-xs text-muted-foreground">{ev.summary}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/30 px-10 py-5">
      {clusters.map((c) => (
        <div
          key={c.block_id}
          className="grid grid-cols-[110px_1fr] gap-7 py-3"
        >
          <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
            {formatHourMinute(c.time_start)}
            <span className="opacity-60"> – {formatHourMinute(c.time_end)}</span>
          </div>
          <div>
            <div className="text-sm text-foreground">{c.label ?? ""}</div>
            {c.summary && (
              <div className="mt-1 text-xs text-muted-foreground">{c.summary}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};
