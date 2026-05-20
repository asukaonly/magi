import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineClusterBlock } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";
import {
  formatDurationCompact,
  groupClustersIntoBuckets,
  type Bucket,
  type SourceGroup,
} from "@/lib/timeline-buckets";

import { SourceIcon, labelForSource } from "./SourceIcon";

interface DayBucketsProps {
  clusters: TimelineClusterBlock[];
}

function formatHourMinute(sec: number): string {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formatTimeRange(startSec: number, endSec: number): string {
  if (Math.abs(endSec - startSec) < 60) {
    return formatHourMinute(startSec);
  }
  return `${formatHourMinute(startSec)} – ${formatHourMinute(endSec)}`;
}

/**
 * Day-scale main content: events grouped into four time-of-day buckets
 * (深夜 / 上午 / 下午 / 晚上). Inside each bucket, source groups are
 * stacked vertically and sorted by total duration descending.
 *
 * Empty buckets are dropped so the page doesn't show a sea of placeholders
 * on quiet days. If *all* buckets are empty, the caller (PeriodCard) should
 * have already routed to its empty state.
 */
export const DayBuckets: React.FC<DayBucketsProps> = ({ clusters }) => {
  const { t } = useTranslation("app");
  const buckets = groupClustersIntoBuckets(clusters).filter((b) => b.groups.length > 0);

  if (buckets.length === 0) {
    return (
      <div className="px-10 py-10 text-center text-sm text-muted-foreground">
        {t("timeline.immersive.dayEmpty", { defaultValue: "这一天没什么动静。" })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-7 px-10 pb-10 pt-3">
      {buckets.map((bucket) => (
        <BucketSection key={bucket.id} bucket={bucket} />
      ))}
    </div>
  );
};

const BucketSection: React.FC<{ bucket: Bucket }> = ({ bucket }) => {
  const { t } = useTranslation("app");
  const headerLabel = t(`timeline.immersive.bucket.${bucket.id}`, {
    defaultValue: bucket.label,
  });

  return (
    <section>
      <header className="mb-3 flex items-baseline gap-2.5">
        <span className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
          {headerLabel}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/60">
          {String(bucket.startHour).padStart(2, "0")}:00 – {String(bucket.endHour).padStart(2, "0")}:00
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground/80">
          {formatDurationCompact(bucket.totalDurationSeconds)}
        </span>
      </header>
      <div className="flex flex-col gap-4">
        {bucket.groups.map((group) => (
          <SourceGroupBlock key={`${bucket.id}-${group.sourceType}`} group={group} />
        ))}
      </div>
    </section>
  );
};

const SourceGroupBlock: React.FC<{ group: SourceGroup }> = ({ group }) => {
  const label = labelForSource(group.sourceType);
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <SourceIcon sourceType={group.sourceType} className="h-3.5 w-3.5" />
        <span className="text-[12px] font-medium text-foreground">{label}</span>
        <span className="font-mono text-[11px] text-muted-foreground/70">
          · {formatDurationCompact(group.totalDurationSeconds)}
        </span>
        {group.itemCount > 1 && (
          <span className="font-mono text-[11px] text-muted-foreground/50">
            · {group.itemCount} 次
          </span>
        )}
      </div>
      <ul className="ml-5 flex flex-col gap-1">
        {group.items.map((item) => (
          <li
            key={item.block_id}
            className={cn(
              "grid grid-cols-[92px_1fr] items-baseline gap-3 text-[13px]",
              "text-foreground/85",
            )}
          >
            <span className="font-mono text-[11px] text-muted-foreground/70">
              {formatTimeRange(item.time_start, item.time_end)}
            </span>
            <span className="leading-snug">
              {item.slice_narrative || item.summary || item.label || ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};
