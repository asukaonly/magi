import { describe, expect, it } from "vitest";

import type { TimelineClusterBlock } from "@/api/modules/timeline";
import {
  bucketIdForTimestamp,
  formatDurationCompact,
  groupClustersIntoBuckets,
  groupClustersIntoWeekDays,
} from "@/lib/timeline-buckets";

/**
 * Helper: build a synthetic cluster with a local-time hour. Other fields are
 * defaulted to keep the test data terse.
 *
 * `localHour` is interpreted as today's hour in the current local timezone —
 * each test that needs deterministic clock behavior should pin the date too.
 */
function cluster(
  partial: Partial<TimelineClusterBlock> & { time_start: number },
): TimelineClusterBlock {
  return {
    block_id: partial.block_id ?? `cluster:${partial.time_start}`,
    time_start: partial.time_start,
    time_end: partial.time_end ?? partial.time_start + 60,
    duration_seconds: partial.duration_seconds ?? 60,
    label: partial.label ?? "",
    summary: partial.summary ?? "",
    dominant_mode: partial.dominant_mode ?? "",
    source_types: partial.source_types ?? ["memory"],
    event_count: partial.event_count ?? 1,
    representative_event_ids: partial.representative_event_ids ?? [],
    keywords: partial.keywords ?? [],
    media_refs: partial.media_refs ?? [],
    state_snapshot: partial.state_snapshot,
    episode_id: partial.episode_id,
    user_label: partial.user_label ?? null,
    user_note: partial.user_note ?? null,
    user_pinned: partial.user_pinned ?? false,
    slice_narrative: partial.slice_narrative,
    slice_sensory_detail: partial.slice_sensory_detail,
    representative_asset_ref: partial.representative_asset_ref,
  };
}

/** Build a Unix-seconds timestamp for the given local-time hour today. */
function todayAt(hour: number, minute = 0): number {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return Math.floor(d.getTime() / 1000);
}

describe("bucketIdForTimestamp", () => {
  it("assigns 02:00 to deep_night (00–05)", () => {
    expect(bucketIdForTimestamp(todayAt(2))).toBe("deep_night");
  });
  it("treats 05:00 as the morning start (boundary)", () => {
    expect(bucketIdForTimestamp(todayAt(5))).toBe("morning");
  });
  it("treats 11:59 as morning, 12:00 as afternoon", () => {
    expect(bucketIdForTimestamp(todayAt(11, 59))).toBe("morning");
    expect(bucketIdForTimestamp(todayAt(12))).toBe("afternoon");
  });
  it("treats 18:00 as evening, 23:59 as evening", () => {
    expect(bucketIdForTimestamp(todayAt(18))).toBe("evening");
    expect(bucketIdForTimestamp(todayAt(23, 59))).toBe("evening");
  });
});

describe("groupClustersIntoBuckets", () => {
  it("returns all 4 buckets in chronological order even when some are empty", () => {
    const buckets = groupClustersIntoBuckets([
      cluster({ time_start: todayAt(2), source_types: ["chrome_history"] }),
    ]);
    expect(buckets.map((b) => b.id)).toEqual([
      "deep_night",
      "morning",
      "afternoon",
      "evening",
    ]);
  });

  it("groups same source within a bucket", () => {
    const buckets = groupClustersIntoBuckets([
      cluster({ time_start: todayAt(8), source_types: ["chrome_history"], duration_seconds: 600 }),
      cluster({ time_start: todayAt(9), source_types: ["chrome_history"], duration_seconds: 1200 }),
      cluster({ time_start: todayAt(10), source_types: ["claude"], duration_seconds: 300 }),
    ]);
    const morning = buckets.find((b) => b.id === "morning")!;
    expect(morning.groups).toHaveLength(2);
    const chrome = morning.groups.find((g) => g.sourceType === "chrome_history");
    expect(chrome?.itemCount).toBe(2);
    expect(chrome?.totalDurationSeconds).toBe(1800);
  });

  it("sorts source groups by total duration descending", () => {
    const buckets = groupClustersIntoBuckets([
      cluster({ time_start: todayAt(8), source_types: ["claude"], duration_seconds: 200 }),
      cluster({ time_start: todayAt(9), source_types: ["chrome_history"], duration_seconds: 4000 }),
      cluster({ time_start: todayAt(10), source_types: ["chat"], duration_seconds: 800 }),
    ]);
    const morning = buckets.find((b) => b.id === "morning")!;
    expect(morning.groups.map((g) => g.sourceType)).toEqual([
      "chrome_history",
      "chat",
      "claude",
    ]);
  });

  it("sorts items within a source group by time_start ascending", () => {
    const buckets = groupClustersIntoBuckets([
      cluster({ block_id: "c1", time_start: todayAt(9), source_types: ["chrome_history"] }),
      cluster({ block_id: "c2", time_start: todayAt(7), source_types: ["chrome_history"] }),
      cluster({ block_id: "c3", time_start: todayAt(8), source_types: ["chrome_history"] }),
    ]);
    const morning = buckets.find((b) => b.id === "morning")!;
    const chrome = morning.groups[0];
    expect(chrome.items.map((i) => i.block_id)).toEqual(["c2", "c3", "c1"]);
  });

  it("falls back to 'memory' when source_types is empty", () => {
    const buckets = groupClustersIntoBuckets([
      cluster({ time_start: todayAt(8), source_types: [] }),
    ]);
    const morning = buckets.find((b) => b.id === "morning")!;
    expect(morning.groups[0].sourceType).toBe("memory");
  });

  it("computes per-bucket total duration as the sum across groups", () => {
    const buckets = groupClustersIntoBuckets([
      cluster({ time_start: todayAt(8), source_types: ["chrome_history"], duration_seconds: 600 }),
      cluster({ time_start: todayAt(9), source_types: ["claude"], duration_seconds: 1200 }),
    ]);
    const morning = buckets.find((b) => b.id === "morning")!;
    expect(morning.totalDurationSeconds).toBe(1800);
  });
});

describe("formatDurationCompact", () => {
  it("renders hours with one decimal when < 2h", () => {
    expect(formatDurationCompact(3600 * 1.5)).toBe("1.5h");
  });
  it("renders hours as integers when >= 2h", () => {
    expect(formatDurationCompact(3600 * 3)).toBe("3h");
  });
  it("renders minutes when < 1h", () => {
    expect(formatDurationCompact(45 * 60)).toBe("45m");
  });
  it("renders seconds when < 1m", () => {
    expect(formatDurationCompact(30)).toBe("30s");
  });
});

describe("groupClustersIntoWeekDays", () => {
  function mondayMidnight(): number {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    const mondayOffset = (d.getDay() + 6) % 7;
    d.setDate(d.getDate() - mondayOffset);
    return Math.floor(d.getTime() / 1000);
  }

  it("always returns 7 day rollups even with no clusters", () => {
    const days = groupClustersIntoWeekDays([], mondayMidnight());
    expect(days).toHaveLength(7);
    expect(days.every((d) => d.items.length === 0)).toBe(true);
  });

  it("assigns clusters to the right day by their local-midnight ISO date", () => {
    const monday = mondayMidnight();
    const wednesdayNoon = monday + 86400 * 2 + 12 * 3600;
    const days = groupClustersIntoWeekDays(
      [cluster({ time_start: wednesdayNoon, source_types: ["chrome_history"], duration_seconds: 600 })],
      monday,
    );
    const wednesday = days[2];
    expect(wednesday.items).toHaveLength(1);
    expect(wednesday.totalDurationSeconds).toBe(600);
    expect(wednesday.topSources[0].sourceType).toBe("chrome_history");
  });

  it("tops out at 3 source chips per day, sorted by duration", () => {
    const monday = mondayMidnight();
    const tuesdayMorning = monday + 86400 + 9 * 3600;
    const days = groupClustersIntoWeekDays(
      [
        cluster({ time_start: tuesdayMorning, source_types: ["chrome_history"], duration_seconds: 100 }),
        cluster({ time_start: tuesdayMorning + 60, source_types: ["claude"], duration_seconds: 2000 }),
        cluster({ time_start: tuesdayMorning + 120, source_types: ["chat"], duration_seconds: 500 }),
        cluster({ time_start: tuesdayMorning + 180, source_types: ["calendar"], duration_seconds: 50 }),
      ],
      monday,
    );
    const tuesday = days[1];
    expect(tuesday.topSources).toHaveLength(3);
    expect(tuesday.topSources.map((s) => s.sourceType)).toEqual([
      "claude",
      "chat",
      "chrome_history",
    ]);
  });
});
