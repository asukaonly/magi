import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router";

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

vi.mock("@/api/modules/manualEntries", async () => {
  const actual = await vi.importActual<typeof import("@/api/modules/manualEntries")>(
    "@/api/modules/manualEntries",
  );
  return {
    ...actual,
    manualEntriesApi: {
      ...actual.manualEntriesApi,
      list: vi.fn().mockResolvedValue([]),
    },
  };
});

import { timelineApi } from "@/api/modules/timeline";
import { TimelinePage } from "@/pages/Timeline";

describe("TimelinePage (immersive)", () => {
  const renderPage = () =>
    render(
      <MemoryRouter>
        <TimelinePage />
      </MemoryRouter>,
    );

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
    (timelineApi.getContext as any).mockResolvedValue({
      anchor: { anchor_id: "episode:ep-a", anchor_type: "episode", title: "ep-a", summary: "" },
      l1_events: [
        {
          event_id: "event-a",
          timestamp: 100,
          title: "聊天",
          summary: "当时留下的原话",
          source_type: "chat",
        },
      ],
      l2_state_evidence: [],
      l3_reflections: [],
      l4_related_procedures: [],
      chat_excerpts: [],
      runtime_trace: [],
    });
  });

  it("renders the immersive page with essence_prose on initial load", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/localhost/)).toBeInTheDocument();
    });
  });

  it("defaults to day scale on mount", async () => {
    renderPage();

    await waitFor(() => {
      expect(timelineApi.getViewport).toHaveBeenCalled();
    });
    const call = (timelineApi.getViewport as any).mock.calls[0][0];
    expect(call.scale).toBe("day");
  });

  it("opens the evidence drawer only after the scene is selected", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findAllByText("narrative");
    expect(document.querySelector("[data-testid='timeline-context-drawer']")).toBeNull();

    const evidenceAction = screen.getByText("查看当时说了什么");
    await user.click(evidenceAction.closest("button")!);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-context-drawer")).toBeInTheDocument();
      expect(screen.getByText("当时留下的原话")).toBeInTheDocument();
    });
  });
});
