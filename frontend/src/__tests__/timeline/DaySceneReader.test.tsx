import i18n from '@/i18n';
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/modules/timeline", async () => {
  const actual = await vi.importActual<typeof import("@/api/modules/timeline")>(
    "@/api/modules/timeline",
  );
  return {
    ...actual,
    timelineApi: {
      ...actual.timelineApi,
      getContext: vi.fn(),
      getEventContext: vi.fn(),
    },
  };
});

import { timelineApi, type TimelineViewportResponse } from "@/api/modules/timeline";
import { DaySceneReader } from "@/components/timeline/immersive/DaySceneReader";

function makeViewport(
  clusterOverrides: Record<string, unknown> = {},
): TimelineViewportResponse {
  const sceneStart = Math.floor(new Date(2026, 6, 23, 22, 31).getTime() / 1000);
  return {
    viewport: {
      scale: "day",
      start: 1_700_000_000,
      end: 1_700_086_400,
      focus: "self",
      query: null,
      timezone: null,
      locale: "zh-CN",
    },
    summary: { event_count: 4, cluster_count: 1, dominant_modes: ["chat"] },
    overview: {
      title: "周四晚间",
      summary: "你和明日香聊起正在听的音乐。",
      key_takeaways: [],
      confidence: 0.8,
      essence_prose: "这个晚上只留下了一段短对话，但它保留了当时的声音。",
    },
    state_summary: {
      mood_label: "",
      stress_label: "",
      engagement_label: "",
      notable_changes: [],
    },
    state_bands: [],
    state_markers: [],
    source_mix: [],
    theme_cards: [],
    clusters: [
      {
        block_id: "cluster-a",
        episode_id: "episode-a",
        time_start: sceneStart,
        time_end: sceneStart + 60,
        duration_seconds: 60,
        label: "activity",
        summary: "明日香说最近在听 DIIV，你追问是《Oshin》还是新专辑。",
        slice_narrative: "“是《Oshin》，还是新专辑？”",
        dominant_mode: "chat",
        source_types: ["chat"],
        event_count: 4,
        representative_event_ids: ["event-a"],
        keywords: [],
        media_refs: [],
        ...clusterOverrides,
      },
    ],
    reflections: [],
    raw_events: [],
  };
}

describe("DaySceneReader", () => {
  it("hides machine titles and runtime-only previews", async () => {
    await i18n.changeLanguage('zh-CN');
    const viewport = makeViewport({ label: 'entity:52b5f111f', slice_narrative: '', summary: 'Codex conversed <environment_context>', source_types: ['codex_agent_history'] });
    render(<DaySceneReader viewport={viewport} dateLabel="11月5日" manualEntries={[]} />);
    expect(screen.getByRole('button', { name: '查看“Codex”的记录' })).toBeInTheDocument();
    expect(screen.queryByText(/entity:|environment_context/)).not.toBeInTheDocument();
  });

  it("loads the complete transient selection and reveals more than thirty records", async () => {
    const entries = Array.from({ length: 35 }, (_, i) => ({event_id: String(i), timestamp: i + 1, title: `Page ${i}`, summary: '', source_type: 'chrome_history'}));
    vi.mocked(timelineApi.getEventContext).mockResolvedValue({anchor: {anchor_id:'selection',anchor_type:'cluster',title:'',summary:''},l1_events:entries,l2_state_evidence:[],l3_reflections:[],l4_related_procedures:[],chat_excerpts:[],runtime_trace:[]});
    const ids = entries.map(item => item.event_id);
    render(<DaySceneReader viewport={makeViewport({episode_id: undefined, source_event_ids: ids})} dateLabel="11月5日" manualEntries={[]} />);
    await userEvent.click(screen.getByRole('button', { name:/查看.*的记录/ }));
    expect(await screen.findByText('Page 29')).toBeInTheDocument();
    expect(screen.queryByText('Page 34')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', {name:/继续显示/}));
    expect(screen.getByText('Page 34')).toBeInTheDocument();
    expect(timelineApi.getEventContext).toHaveBeenCalledWith(ids);
  });

  it("ignores a late response after closing and reopening another record", async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof timelineApi.getContext>>) => void;
    vi.mocked(timelineApi.getContext).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const viewport = makeViewport();
    viewport.clusters.push({...viewport.clusters[0], block_id:'cluster-b', episode_id:'episode-b', label:'Second record'});
    render(<DaySceneReader viewport={viewport} dateLabel="11月5日" manualEntries={[]} />);
    await userEvent.click(screen.getAllByRole('button', {name:/查看.*的记录/})[0]);
    await userEvent.click(screen.getByRole('button', {name:'返回当天'}));
    await userEvent.click(screen.getByRole('button', {name:'查看“Second record”的记录'}));
    expect(await screen.findByText('我最近在听 DIIV，挺好听。')).toBeInTheDocument();
    await act(async () => resolveOld({anchor:{anchor_id:'old',anchor_type:'episode',title:'',summary:''},l1_events:[{event_id:'old',summary:'Stale content'}],l2_state_evidence:[],l3_reflections:[],l4_related_procedures:[],chat_excerpts:[],runtime_trace:[]}));
    expect(screen.queryByText('Stale content')).not.toBeInTheDocument();
  });
  beforeEach(async () => {
    await i18n.changeLanguage("zh-CN");
    vi.clearAllMocks();
    vi.mocked(timelineApi.getContext).mockResolvedValue({
      anchor: {
        anchor_id: "episode:episode-a",
        anchor_type: "episode",
        title: "episode-a",
        summary: "",
      },
      l1_events: [
        {
          event_id: "event-a",
          timestamp: 1_700_080_260,
          title: "对话",
          summary: "我最近在听 DIIV，挺好听。",
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

  it("shows a real chapter only when a persisted chapter is present", () => {
    render(
      <DaySceneReader
        viewport={makeViewport({
          experience_id: "experience-a",
          experience_title: "在音乐里认识彼此",
          experience_chapter_id: "chapter-a",
          experience_chapter_title: "DIIV 的新旧声音",
        })}
        dateLabel="2026年7月23日"
        manualEntries={[]}
      />,
    );

    expect(screen.getByRole("heading", { name: "2026年7月23日" })).toBeInTheDocument();
    expect(screen.getByText(/在音乐里认识彼此/)).toHaveTextContent("经历章节");
    expect(screen.queryByText(/经历中的一天/)).not.toBeInTheDocument();
  });

  it("keeps an experience member without a chapter labeled as a fragment", () => {
    render(
      <DaySceneReader
        viewport={makeViewport({
          experience_id: "experience-a",
          experience_title: "在音乐里认识彼此",
        })}
        dateLabel="2026年7月23日"
        manualEntries={[]}
      />,
    );

    expect(screen.getByText(/在音乐里认识彼此/)).toBeInTheDocument();
    expect(screen.queryByText(/经历章节/)).not.toBeInTheDocument();
  });

  it("shows an independent fragment and exposes the organize action", async () => {
    const user = userEvent.setup();
    const onOrganize = vi.fn();
    render(
      <DaySceneReader
        viewport={makeViewport()}
        dateLabel="2026年7月23日"
        manualEntries={[]}
        onOrganizeExperience={onOrganize}
      />,
    );

    expect(screen.queryByText("尚未形成经历")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /整理为经历/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /查看.*的记录/ }));
    await user.click(screen.getByRole("button", { name: /整理为经历/ }));
    expect(onOrganize).toHaveBeenCalledOnce();
  });

  it("keeps evidence collapsed until a scene is opened, then closes it again", async () => {
    const user = userEvent.setup();
    render(
      <DaySceneReader
        viewport={makeViewport()}
        dateLabel="2026年7月23日"
        manualEntries={[]}
      />,
    );

    expect(screen.queryByTestId("timeline-context-drawer")).not.toBeInTheDocument();
    const evidenceAction = screen.getByRole("button", { name: /查看.*的记录/ });
    const sceneButton = evidenceAction.closest("button")!;
    expect(sceneButton).toHaveAttribute("aria-expanded", "false");
    await user.click(sceneButton);

    await waitFor(() => {
      expect(screen.getByTestId("timeline-context-drawer")).toHaveFocus();
      expect(screen.getByText("我最近在听 DIIV，挺好听。")).toBeInTheDocument();
    });
    expect(sceneButton).toHaveAttribute("aria-expanded", "true");
    expect(timelineApi.getContext).toHaveBeenCalledWith("episode:episode-a");

    await user.click(screen.getByRole("button", { name: "返回当天" }));
    await waitFor(() => {
      expect(screen.queryByTestId("timeline-context-drawer")).not.toBeInTheDocument();
      expect(sceneButton).toHaveFocus();
    });
  });

  it("closes the old evidence drawer when the selected day changes", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <DaySceneReader
        viewport={makeViewport()}
        dateLabel="2026年7月23日"
        manualEntries={[]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /查看.*的记录/ }).closest("button")!);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-context-drawer")).toBeInTheDocument();
    });

    const nextDay = makeViewport();
    nextDay.viewport.start += 86_400;
    nextDay.viewport.end += 86_400;
    rerender(
      <DaySceneReader
        viewport={nextDay}
        dateLabel="2026年7月24日"
        manualEntries={[]}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByTestId("timeline-context-drawer")).not.toBeInTheDocument();
    });
  });

  it("does not repeat a chat record in both drawer sections", async () => {
    vi.mocked(timelineApi.getContext).mockResolvedValue({
      anchor: {
        anchor_id: "episode:episode-a",
        anchor_type: "episode",
        title: "episode-a",
        summary: "",
      },
      l1_events: [
        {
          event_id: "event-a",
          timestamp: 1_700_080_260,
          title: "对话",
          summary: "只显示一次的原始对话。",
          source_type: "chat",
        },
      ],
      l2_state_evidence: [],
      l3_reflections: [],
      l4_related_procedures: [],
      chat_excerpts: [
        {
          event_id: "event-a",
          content: "只显示一次的原始对话。",
        },
      ],
      runtime_trace: [],
    });
    const user = userEvent.setup();
    render(
      <DaySceneReader
        viewport={makeViewport()}
        dateLabel="2026年7月23日"
        manualEntries={[]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /查看.*的记录/ }).closest("button")!);
    await waitFor(() => {
      expect(screen.getAllByText("只显示一次的原始对话。")).toHaveLength(1);
    });
    expect(screen.queryByText("来源事实")).not.toBeInTheDocument();
    expect(screen.queryByText("原始对话")).not.toBeInTheDocument();
  });
});
