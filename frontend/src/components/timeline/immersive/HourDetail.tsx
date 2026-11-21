import React from "react";
import { useTranslation } from "react-i18next";

import type { ManualEntry } from "@/api/modules/manualEntries";
import type { TimelineViewportResponse } from "@/api/modules/timeline";

interface HourDetailProps {
  viewport: TimelineViewportResponse;
  manualEntries?: ManualEntry[];
  onEditManualEntry?: (entry: ManualEntry) => void;
  onDeleteManualEntry?: (entryId: string) => void;
}

function formatHourMinute(sec: number): string {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * Hour scale = "侦探模式": raw L1 events and manual entries shown as a
 * chronological evidence list. The backend deliberately ships clusters=[] at
 * hour scale so we don't cluster too aggressively at minute granularity.
 *
 * Falls back to rendering clusters when raw_events is empty (defensive — some
 * historical viewport responses may still carry them).
 */
export const HourDetail: React.FC<HourDetailProps> = ({
  viewport,
  manualEntries = [],
  onEditManualEntry,
  onDeleteManualEntry,
}) => {
  const { t } = useTranslation("app");
  const clusters = viewport.clusters ?? [];
  const rawEvents = viewport.raw_events ?? [];

  if (clusters.length === 0 && rawEvents.length === 0 && manualEntries.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
        {t("timeline.immersive.hourEmpty", { defaultValue: "这个小时没什么动静。" })}
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/30 px-10 py-5">
      {manualEntries.map((entry) => (
        <div
          key={`manual-${entry.entry_id}`}
          data-testid="hour-manual-entry"
          className="grid grid-cols-[110px_1fr] gap-7 py-3"
        >
          <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
            {formatHourMinute(entry.event_at)}
          </div>
          <div className="min-w-0">
            <div className="flex items-start justify-between gap-4">
              <div className="whitespace-pre-wrap text-sm text-foreground">{entry.body}</div>
              {(onEditManualEntry || onDeleteManualEntry) ? (
                <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                  {onEditManualEntry ? (
                    <button
                      type="button"
                      onClick={() => onEditManualEntry(entry)}
                      className="underline-offset-4 hover:text-foreground hover:underline"
                    >
                      {t("timeline.manualEntry.editAction", { defaultValue: "编辑" })}
                    </button>
                  ) : null}
                  {onDeleteManualEntry ? (
                    <button
                      type="button"
                      onClick={() => onDeleteManualEntry(entry.entry_id)}
                      className="underline-offset-4 hover:text-destructive hover:underline"
                    >
                      {t("timeline.manualEntry.deleteAction", { defaultValue: "删除" })}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
            {entry.location_label ? (
              <div className="mt-1 text-xs text-muted-foreground">{entry.location_label}</div>
            ) : null}
          </div>
        </div>
      ))}
      {rawEvents.length > 0
        ? rawEvents.map((ev) => (
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
          ))
        : clusters.map((c) => (
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
