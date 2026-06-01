import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { Slice } from "@/components/timeline/immersive/Slice";

const baseProps = {
  episodeId: "ep-x",
  timeRangeLabel: "14:00 – 17:00",
  narrative: "下午你读了 timeline-domain 的架构文档。",
  isPinned: false,
  onTogglePinned: vi.fn(),
  onHide: vi.fn(),
};

describe("Slice", () => {
  it("renders time range, narrative, and optional sensory detail", () => {
    render(<Slice {...baseProps} sensoryDetail="窗外光线很柔。" />);

    expect(screen.getByText("14:00 – 17:00")).toBeInTheDocument();
    expect(screen.getByText(/下午你读了/)).toBeInTheDocument();
    expect(screen.getByText("窗外光线很柔。")).toBeInTheDocument();
  });

  it("calls onTogglePinned with next=true when ♡ is clicked on an unpinned slice", async () => {
    const user = userEvent.setup();
    const toggle = vi.fn();
    render(<Slice {...baseProps} onTogglePinned={toggle} />);

    const heart = screen.getByRole("button", { name: /想常回来|喜欢|♡/i });
    await user.click(heart);
    expect(toggle).toHaveBeenCalledWith("ep-x", true);
  });

  it("shows a solid ♡ when isPinned is true and toggles to false on click", async () => {
    const user = userEvent.setup();
    const toggle = vi.fn();
    render(<Slice {...baseProps} isPinned onTogglePinned={toggle} />);

    const heart = screen.getByRole("button", { name: /想常回来|喜欢|♡/i });
    expect(heart).toHaveAttribute("data-pinned", "true");

    await user.click(heart);
    expect(toggle).toHaveBeenCalledWith("ep-x", false);
  });

  it("opens the ⋯ menu and triggers onHide", async () => {
    const user = userEvent.setup();
    const hide = vi.fn();
    render(<Slice {...baseProps} onHide={hide} />);

    const menuButton = screen.getByRole("button", { name: /more|更多|⋯/i });
    await user.click(menuButton);
    const hideItem = await screen.findByText(/不算这天的样子/);
    await user.click(hideItem);

    expect(hide).toHaveBeenCalledWith("ep-x");
  });
});
