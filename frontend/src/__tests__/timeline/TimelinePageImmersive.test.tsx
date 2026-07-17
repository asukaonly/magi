import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the API modules BEFORE importing the page
vi.mock("@/api/modules/timeline", async () => {
  const actual = await vi.importActual<typeof import("@/api/modules/timeline")>(
    "@/api/modules/timeline"
  );
  return {
    ...actual,
    timelineApi: {
      getViewport: vi.fn(),
      getContext: vi.fn(),
      getStandout: vi.fn(),
      getMoodCalendar: vi.fn(),
      setCoverPreference: vi.fn(),
    },
  };
});

vi.mock("@/api/modules/memory", () => ({
  memoryApi: {
    annotateEpisode: vi.fn(),
    forgetEpisode: vi.fn(),
    submitAssertionFeedback: vi.fn(),
  },
}));

import { timelineApi } from "@/api/modules/timeline";
import { TimelinePage } from "@/pages/Timeline";

describe("TimelinePage (immersive)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (timelineApi.getViewport as any).mockResolvedValue({
      viewport: { scale: "day", start: 0, end: 86400, focus: 0, query: null, timezone: null, locale: "zh" },
      summary: { event_count: 1, cluster_count: 1, dominant_modes: [] },
      overview: {
        title: "test day",
        summary: "",
        key_takeaways: [],
        essence_prose: "周日。你大部分时间在 localhost 之间游走。",
      },
      state_summary: { dominant_valence: "cool", volatility: 0.4, notable_changes: [] },
      state_bands: [],
      state_markers: [],
      source_mix: [],
      theme_cards: [],
      clusters: [{
        episode_id: "ep-a",
        time_start: 100,
        time_end: 200,
        label: "x",
        slice_narrative: "narrative",
        user_pinned: false,
      }],
      reflections: [],
      raw_events: [],
    });
    (timelineApi.getStandout as any).mockResolvedValue({ month: null, items: [] }); // options-object signature
    (timelineApi.getMoodCalendar as any).mockResolvedValue({ month: "2026-05", days: [] });
  });

  it("renders the immersive page with essence_prose on initial load", async () => {
    render(<TimelinePage />);

    await waitFor(() => {
      expect(screen.getByText(/localhost/)).toBeInTheDocument();
    });
  });

  it("defaults to day scale on mount", async () => {
    render(<TimelinePage />);

    await waitFor(() => {
      expect(timelineApi.getViewport).toHaveBeenCalled();
    });
    const call = (timelineApi.getViewport as any).mock.calls[0][0];
    expect(call.scale).toBe("day");
  });

  it("does not render a TimelineContextDrawer", () => {
    render(<TimelinePage />);
    expect(document.querySelector("[data-testid='timeline-context-drawer']")).toBeNull();
  });
});
