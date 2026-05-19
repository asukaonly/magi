import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { MoodCalendar } from "@/components/timeline/immersive/sidebar/MoodCalendar";

describe("MoodCalendar", () => {
  it("renders 7 weekday headers", () => {
    render(
      <MoodCalendar
        month="2026-05"
        days={[]}
        selectedDate="2026-05-17"
        onSelectDate={vi.fn()}
      />
    );
    const headers = screen.getAllByRole("columnheader");
    expect(headers.length).toBe(7);
  });

  it("highlights the selected date cell", () => {
    render(
      <MoodCalendar
        month="2026-05"
        days={[{
          date: "2026-05-17",
          dominant_valence: "cool",
          volatility: 0.6,
          event_count: 228,
          sparkline: [],
        }]}
        selectedDate="2026-05-17"
        onSelectDate={vi.fn()}
      />
    );
    const selected = screen.getByRole("button", { name: /2026-05-17/ });
    expect(selected).toHaveAttribute("data-selected", "true");
  });

  it("calls onSelectDate when a day cell is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <MoodCalendar
        month="2026-05"
        days={[
          { date: "2026-05-10", dominant_valence: "warm", volatility: 0.2, event_count: 42, sparkline: [] },
        ]}
        selectedDate="2026-05-17"
        onSelectDate={onSelect}
      />
    );
    const cell = screen.getByRole("button", { name: /2026-05-10/ });
    await user.click(cell);
    expect(onSelect).toHaveBeenCalledWith("2026-05-10");
  });
});
