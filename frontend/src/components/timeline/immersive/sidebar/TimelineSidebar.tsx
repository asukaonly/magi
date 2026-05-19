import React from "react";

import type {
  TimelineMoodCalendarDay,
  TimelineStandoutItem,
} from "@/api/modules/timeline";

import { MoodCalendar } from "./MoodCalendar";
import { StandoutList } from "./StandoutList";

interface TimelineSidebarProps {
  monthForCalendar: string;  // "YYYY-MM"
  moodDays: TimelineMoodCalendarDay[];
  standoutItems: TimelineStandoutItem[];
  selectedDate: string;
  onSelectDate: (isoDate: string) => void;
  onSelectStandoutEpisode: (episodeId: string) => void;
}

export const TimelineSidebar: React.FC<TimelineSidebarProps> = ({
  monthForCalendar,
  moodDays,
  standoutItems,
  selectedDate,
  onSelectDate,
  onSelectStandoutEpisode,
}) => {
  return (
    <aside className="w-[260px] shrink-0 overflow-y-auto border-r border-border/40 bg-[#f4ede0]">
      <MoodCalendar
        month={monthForCalendar}
        days={moodDays}
        selectedDate={selectedDate}
        onSelectDate={onSelectDate}
      />
      <StandoutList
        items={standoutItems}
        onSelectEpisode={onSelectStandoutEpisode}
      />
    </aside>
  );
};
