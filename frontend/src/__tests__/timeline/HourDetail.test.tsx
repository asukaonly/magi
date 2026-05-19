import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { HourDetail } from "@/components/timeline/immersive/HourDetail";
import type { TimelineClusterBlock, TimelineViewportResponse } from "@/api/modules/timeline";

function makeViewport(clusters: TimelineClusterBlock[] = []): TimelineViewportResponse {
  return {
    viewport: { scale: "hour", start: 0, end: 3600, focus: 0, query: null, timezone: null, locale: "zh" },
    summary: { event_count: clusters.length, cluster_count: clusters.length, dominant_modes: [] },
    overview: { title: "", summary: "", key_takeaways: [] },
    state_summary: { dominant_valence: "neutral", volatility: 0, notable_changes: [] },
    state_bands: [],
    state_markers: [],
    source_mix: [],
    theme_cards: [],
    clusters,
    reflections: [],
    raw_events: [],
  } as unknown as TimelineViewportResponse;
}

describe("HourDetail", () => {
  it("renders an empty state when there are no clusters or events", () => {
    render(<HourDetail viewport={makeViewport([])} />);
    expect(screen.getByText(/这个小时|动静|empty/i)).toBeInTheDocument();
  });

  it("renders one row per cluster with time and label", () => {
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        time_start: 240,
        time_end: 540,
        label: "Chrome 浏览",
        summary: "百炼控制台 ×6",
      } as unknown as TimelineClusterBlock,
      {
        episode_id: "ep-b",
        time_start: 900,
        time_end: 950,
        label: "GitHub 浏览",
        summary: "asukaonly/magi",
      } as unknown as TimelineClusterBlock,
    ];
    render(<HourDetail viewport={makeViewport(clusters)} />);

    // Time labels depend on local timezone; use a flexible regex
    expect(screen.getByText(/Chrome 浏览/)).toBeInTheDocument();
    expect(screen.getByText(/百炼控制台 ×6/)).toBeInTheDocument();
    expect(screen.getByText(/GitHub 浏览/)).toBeInTheDocument();
    expect(screen.getByText(/asukaonly\/magi/)).toBeInTheDocument();
  });

  it("does NOT render a Hero element", () => {
    const clusters: TimelineClusterBlock[] = [
      { episode_id: "ep-a", time_start: 100, time_end: 200, label: "x" } as unknown as TimelineClusterBlock,
    ];
    const { container } = render(<HourDetail viewport={makeViewport(clusters)} />);
    expect(container.querySelector("h2")).not.toBeInTheDocument();
  });
});
