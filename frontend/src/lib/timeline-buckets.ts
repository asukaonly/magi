/**
 * Pure aggregation: turn a flat list of timeline clusters into time-of-day
 * buckets, each with source-grouped rows sorted by total duration.
 *
 * Bucket boundaries (per design discussion):
 *   深夜 00:00 – 05:00
 *   上午 05:00 – 12:00
 *   下午 12:00 – 18:00
 *   晚上 18:00 – 24:00
 *
 * A cluster is assigned to a single bucket based on its `time_start` in
 * local time. Clusters crossing a boundary (e.g. a 04:30–06:00 episode)
 * still go in the bucket containing their start — splitting them would
 * fragment narratives without any reader benefit.
 */

import type { TimelineClusterBlock } from "@/api/modules/timeline";

export type BucketId = "deep_night" | "morning" | "afternoon" | "evening";

export interface BucketDefinition {
  id: BucketId;
  /** Inclusive lower bound (local hour 0–23). */
  startHour: number;
  /** Exclusive upper bound (local hour 1–24). */
  endHour: number;
  /** zh-CN label. UI may i18n-lookup an override. */
  label: string;
}

/** Canonical bucket definitions, ordered chronologically. */
export const BUCKET_DEFS: readonly BucketDefinition[] = [
  { id: "deep_night", startHour: 0, endHour: 5, label: "深夜" },
  { id: "morning", startHour: 5, endHour: 12, label: "上午" },
  { id: "afternoon", startHour: 12, endHour: 18, label: "下午" },
  { id: "evening", startHour: 18, endHour: 24, label: "晚上" },
] as const;

export interface SourceGroup {
  /** First source_type on the constituent clusters; "memory" when none. */
  sourceType: string;
  /** Sum of duration_seconds across items. */
  totalDurationSeconds: number;
  /** Cluster count in this group. */
  itemCount: number;
  /** Items sorted by time_start ascending. */
  items: TimelineClusterBlock[];
}

export interface Bucket {
  id: BucketId;
  label: string;
  startHour: number;
  endHour: number;
  /** Source groups sorted by totalDurationSeconds descending. */
  groups: SourceGroup[];
  /** Convenience: sum of all group durations in this bucket. */
  totalDurationSeconds: number;
}

/**
 * Return the bucket id whose [startHour, endHour) contains the given
 * local-time timestamp. Falls back to "evening" if hour is out of range
 * (defensive — shouldn't happen with valid Date input).
 */
export function bucketIdForTimestamp(timestampSec: number): BucketId {
  const hour = new Date(timestampSec * 1000).getHours();
  for (const def of BUCKET_DEFS) {
    if (hour >= def.startHour && hour < def.endHour) return def.id;
  }
  return "evening";
}

/** Take the primary source_type from a cluster, defaulting to "memory". */
function primarySourceType(cluster: TimelineClusterBlock): string {
  const first = (cluster.source_types ?? [])[0];
  return (first && first.trim()) || "memory";
}

/**
 * Aggregate clusters into the four time-of-day buckets, grouping rows by
 * source_type within each bucket. Returns *all four* bucket positions even
 * when empty so the day rhythm reads coherently (an empty 上午 says "you
 * weren't online this morning"). Callers may filter empties for compactness.
 *
 * Sort rules:
 *   - Buckets: chronological (BUCKET_DEFS order)
 *   - Source groups within a bucket: total duration descending
 *   - Items within a source group: time_start ascending
 */
export function groupClustersIntoBuckets(
  clusters: readonly TimelineClusterBlock[],
): Bucket[] {
  // bucketId → sourceType → SourceGroup-in-progress
  const accumulator = new Map<BucketId, Map<string, SourceGroup>>();
  for (const def of BUCKET_DEFS) {
    accumulator.set(def.id, new Map());
  }

  for (const cluster of clusters) {
    const bucketId = bucketIdForTimestamp(cluster.time_start);
    const groupsByType = accumulator.get(bucketId)!;
    const sourceType = primarySourceType(cluster);
    let group = groupsByType.get(sourceType);
    if (!group) {
      group = {
        sourceType,
        totalDurationSeconds: 0,
        itemCount: 0,
        items: [],
      };
      groupsByType.set(sourceType, group);
    }
    group.items.push(cluster);
    group.itemCount += 1;
    group.totalDurationSeconds += Math.max(0, cluster.duration_seconds || 0);
  }

  return BUCKET_DEFS.map((def) => {
    const groupsByType = accumulator.get(def.id)!;
    // Sort items inside each group chronologically.
    for (const group of groupsByType.values()) {
      group.items.sort((a, b) => a.time_start - b.time_start);
    }
    const groups = Array.from(groupsByType.values()).sort(
      (a, b) => b.totalDurationSeconds - a.totalDurationSeconds,
    );
    const totalDurationSeconds = groups.reduce(
      (sum, g) => sum + g.totalDurationSeconds,
      0,
    );
    return {
      id: def.id,
      label: def.label,
      startHour: def.startHour,
      endHour: def.endHour,
      groups,
      totalDurationSeconds,
    };
  });
}

/** Format a duration in seconds as a compact label like "3h" / "45m" / "30s". */
export function formatDurationCompact(durationSeconds: number): string {
  if (durationSeconds >= 3600) {
    const hours = durationSeconds / 3600;
    return hours >= 2 ? `${Math.round(hours)}h` : `${hours.toFixed(1)}h`;
  }
  if (durationSeconds >= 60) {
    return `${Math.round(durationSeconds / 60)}m`;
  }
  return `${Math.round(durationSeconds)}s`;
}

// ─────────────────────────────────────────────────────────────────────
// Week-scale: per-day rollup
// ─────────────────────────────────────────────────────────────────────

export interface DayRollup {
  /** YYYY-MM-DD in local time. */
  isoDate: string;
  /** Unix seconds at local midnight of this day. */
  dayStart: number;
  /** Weekday label (zh-CN: 一二三四五六日). */
  weekdayLabel: string;
  /** Total seconds of activity on this day. */
  totalDurationSeconds: number;
  /** Top-N source types by total duration, with their sum. */
  topSources: Array<{ sourceType: string; durationSeconds: number }>;
  /** Underlying cluster items for this day (for click-through). */
  items: TimelineClusterBlock[];
}

const WEEKDAY_LABELS_ZH = ["日", "一", "二", "三", "四", "五", "六"] as const;

/** ISO day key in local time for use as Map key. */
function localIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/**
 * Roll clusters up into 7 per-day cards spanning a week starting at
 * `weekStartSec` (Monday 00:00 local). Empty days are kept in the result so
 * the strip always has 7 slots (calendar weeks aren't all "active" days).
 */
export function groupClustersIntoWeekDays(
  clusters: readonly TimelineClusterBlock[],
  weekStartSec: number,
): DayRollup[] {
  // Pre-seed 7 day buckets so empty days still show in the strip.
  const days: DayRollup[] = [];
  for (let i = 0; i < 7; i++) {
    const dayDate = new Date(weekStartSec * 1000);
    dayDate.setDate(dayDate.getDate() + i);
    dayDate.setHours(0, 0, 0, 0);
    days.push({
      isoDate: localIsoDate(dayDate),
      dayStart: Math.floor(dayDate.getTime() / 1000),
      weekdayLabel: `周${WEEKDAY_LABELS_ZH[dayDate.getDay()]}`,
      totalDurationSeconds: 0,
      topSources: [],
      items: [],
    });
  }

  const byIsoDate = new Map(days.map((d) => [d.isoDate, d]));
  const sourceTotalsByDay = new Map<string, Map<string, number>>();

  for (const cluster of clusters) {
    const startDate = new Date(cluster.time_start * 1000);
    const iso = localIsoDate(startDate);
    const day = byIsoDate.get(iso);
    if (!day) continue;
    day.items.push(cluster);
    day.totalDurationSeconds += Math.max(0, cluster.duration_seconds || 0);
    const sourceType = primarySourceType(cluster);
    let perSource = sourceTotalsByDay.get(iso);
    if (!perSource) {
      perSource = new Map();
      sourceTotalsByDay.set(iso, perSource);
    }
    perSource.set(
      sourceType,
      (perSource.get(sourceType) || 0) + Math.max(0, cluster.duration_seconds || 0),
    );
  }

  // Finalize: sort items + compute top sources
  for (const day of days) {
    day.items.sort((a, b) => a.time_start - b.time_start);
    const perSource = sourceTotalsByDay.get(day.isoDate);
    if (perSource) {
      day.topSources = Array.from(perSource.entries())
        .map(([sourceType, durationSeconds]) => ({ sourceType, durationSeconds }))
        .sort((a, b) => b.durationSeconds - a.durationSeconds)
        .slice(0, 3);
    }
  }

  return days;
}
