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

  return (
    <div className="divide-y divide-border/30 px-10 py-5">
      {clusters.map((c) => (
        <div
          key={c.episode_id ?? `${c.time_start}`}
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
