import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { StandoutList } from "@/components/timeline/immersive/sidebar/StandoutList";
import type { TimelineStandoutItem } from "@/api/modules/timeline";

const items: TimelineStandoutItem[] = [
  {
    episode_id: "ep-1",
    scale: "day",
    start: 1,
    end: 2,
    title: "第一次跑通 ChatTaskAgent",
    date: "2026-05-12",
    source: "magi",
    score: 0.8,
  },
  {
    episode_id: "ep-2",
    scale: "day",
    start: 3,
    end: 4,
    title: "跟 Z 在文渊喝咖啡",
    date: "2026-05-14",
    source: "user",
    score: 0.0,
  },
];

describe("StandoutList", () => {
  it("renders title and date for each item", () => {
    render(<StandoutList items={items} onSelectEpisode={vi.fn()} />);
    expect(screen.getByText("第一次跑通 ChatTaskAgent")).toBeInTheDocument();
    expect(screen.getByText("2026-05-12")).toBeInTheDocument();
    expect(screen.getByText("跟 Z 在文渊喝咖啡")).toBeInTheDocument();
  });

  it("prefixes user-pinned items with ♡ and not magi items", () => {
    render(<StandoutList items={items} onSelectEpisode={vi.fn()} />);
    const userItem = screen.getByText("跟 Z 在文渊喝咖啡").closest("button");
    const magiItem = screen.getByText("第一次跑通 ChatTaskAgent").closest("button");
    expect(userItem?.textContent).toMatch(/♡/);
    expect(magiItem?.textContent).not.toMatch(/♡/);
  });

  it("calls onSelectEpisode when an item is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<StandoutList items={items} onSelectEpisode={onSelect} />);
    await user.click(screen.getByText("第一次跑通 ChatTaskAgent"));
    expect(onSelect).toHaveBeenCalledWith("ep-1");
  });

  it("renders the empty-state placeholder when items is empty", () => {
    render(<StandoutList items={[]} onSelectEpisode={vi.fn()} />);
    expect(screen.getByText(/再陪你几天/)).toBeInTheDocument();
  });
});
