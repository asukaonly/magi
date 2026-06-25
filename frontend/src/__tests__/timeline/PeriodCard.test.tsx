import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { PeriodCard } from "@/components/timeline/immersive/PeriodCard";
import type {
  TimelineClusterBlock,
  TimelineThemeCard,
  TimelineViewportResponse,
} from "@/api/modules/timeline";

function makeViewport(overrides: Partial<TimelineViewportResponse> = {}): TimelineViewportResponse {
  return {
    viewport: { scale: "day", start: 0, end: 86400, focus: 0, query: null, timezone: null, locale: "zh" },
    summary: { event_count: 0, cluster_count: 0, dominant_modes: [] },
    overview: {
      title: "5/17 周日",
      summary: "fallback summary",
      key_takeaways: [],
      essence_prose: "周日。你大部分时间在 localhost 之间游走。",
    },
    state_summary: { dominant_valence: "cool", volatility: 0.4, notable_changes: [] },
    state_bands: [],
    state_markers: [],
    source_mix: [],
    theme_cards: [],
    clusters: [],
    reflections: [],
    raw_events: [],
    ...overrides,
  } as unknown as TimelineViewportResponse;
}

describe("PeriodCard", () => {
  it("renders Hero with essence_prose from overview", () => {
    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport()}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText(/localhost/)).toBeInTheDocument();
  });

  it("renders one Slice per cluster", () => {
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        time_start: 0,
        time_end: 3600,
        label: "morning",
        slice_narrative: "上午你在调试。",
        user_pinned: false,
      } as unknown as TimelineClusterBlock,
      {
        episode_id: "ep-b",
        time_start: 7200,
        time_end: 10800,
        label: "afternoon",
        slice_narrative: "下午你换了一个新方向。",
        user_pinned: true,
      } as unknown as TimelineClusterBlock,
    ];

    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({ clusters })}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText("上午你在调试。")).toBeInTheDocument();
    expect(screen.getByText("下午你换了一个新方向。")).toBeInTheDocument();
  });

  it("renders ThemesRow when theme_cards is non-empty", () => {
    const themes: TimelineThemeCard[] = [
      { theme_id: "t1", title: "portrait rail", source_count: 0, evidence_anchors: [] } as unknown as TimelineThemeCard,
      { theme_id: "t2", title: "timeline-domain", source_count: 0, evidence_anchors: [] } as unknown as TimelineThemeCard,
    ];
    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({ theme_cards: themes })}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText("portrait rail")).toBeInTheDocument();
    expect(screen.getByText("timeline-domain")).toBeInTheDocument();
  });

  it("renders PeriodCardEmpty when viewport has zero events, zero clusters, and no essence_prose", () => {
    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({ overview: { title: "", summary: "", key_takeaways: [], essence_prose: "" } as any })}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText(/再陪你几天/)).toBeInTheDocument();
  });

  it("uses a manually selected timeline cover over the automatic cluster photo", () => {
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        block_id: "cluster-a",
        time_start: 0,
        time_end: 3600,
        label: "morning",
        representative_asset_ref: "photo-library://auto",
      } as unknown as TimelineClusterBlock,
    ];

    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({
          clusters,
          cover: {
            mode: "asset",
            asset_ref: "photo-library://manual",
            source: "current_period",
            candidates: [],
          },
        } as Partial<TimelineViewportResponse>)}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByAltText("hero photo")).toHaveAttribute(
      "src",
      expect.stringContaining("photo-library%3A%2F%2Fmanual")
    );
  });

  it("hides the hero image when the cover is hidden", () => {
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        block_id: "cluster-a",
        time_start: 0,
        time_end: 3600,
        label: "morning",
        representative_asset_ref: "photo-library://auto",
      } as unknown as TimelineClusterBlock,
    ];

    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({
          clusters,
          cover: {
            mode: "hidden",
            asset_ref: null,
            source: "hidden",
            candidates: [],
          },
        } as Partial<TimelineViewportResponse>)}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.queryByAltText("hero photo")).not.toBeInTheDocument();
  });

  it("lets the user choose, hide, and restore the cover", async () => {
    const user = userEvent.setup();
    const onChangeCover = vi.fn().mockResolvedValue(undefined);
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        block_id: "cluster-a",
        time_start: 0,
        time_end: 3600,
        label: "morning",
        representative_asset_ref: "photo-library://asset-a",
      } as unknown as TimelineClusterBlock,
    ];

    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({
          clusters,
          cover: {
            mode: "auto",
            asset_ref: "photo-library://asset-a",
            source: "auto",
            candidates: [
              {
                asset_ref: "photo-library://asset-a",
                source: "current_period",
                label: "晨间照片",
                cluster_id: "cluster-a",
              },
            ],
          },
        } as Partial<TimelineViewportResponse>)}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
        onChangeCover={onChangeCover}
      />
    );

    await user.click(screen.getByRole("button", { name: "更换封面" }));
    const sheet = screen.getByRole("dialog", { name: "更换封面" });
    await user.click(within(sheet).getByRole("button", { name: "晨间照片" }));
    await user.click(within(sheet).getByRole("button", { name: "设为封面" }));
    expect(onChangeCover).toHaveBeenCalledWith({
      mode: "asset",
      asset_ref: "photo-library://asset-a",
      source: "current_period",
    });

    await user.click(within(sheet).getByRole("button", { name: "隐藏封面" }));
    expect(onChangeCover).toHaveBeenCalledWith({ mode: "hidden" });

    await user.click(within(sheet).getByRole("button", { name: "恢复自动" }));
    expect(onChangeCover).toHaveBeenCalledWith({ mode: "auto" });
  });

  it("uploads a custom local image and uses a wider picker", async () => {
    const user = userEvent.setup();
    const onChangeCover = vi.fn().mockResolvedValue(undefined);
    const onUploadCover = vi.fn().mockResolvedValue("manual-entry-asset://custom-cover.jpg");

    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({
          cover: {
            mode: "auto",
            asset_ref: null,
            source: "auto",
            candidates: [],
          },
        } as Partial<TimelineViewportResponse>)}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
        onChangeCover={onChangeCover}
        onUploadCover={onUploadCover}
      />
    );

    await user.click(screen.getByRole("button", { name: "更换封面" }));
    const sheet = screen.getByRole("dialog", { name: "更换封面" });
    expect(sheet).toHaveClass("w-[560px]");

    const file = new File(["cover"], "cover.jpg", { type: "image/jpeg" });
    await user.upload(within(sheet).getByTestId("timeline-cover-upload-input"), file);

    expect(onUploadCover).toHaveBeenCalledWith(file);
    expect(onChangeCover).toHaveBeenCalledWith({
      mode: "asset",
      asset_ref: "manual-entry-asset://custom-cover.jpg",
      source: "custom_upload",
    });
  });
});
