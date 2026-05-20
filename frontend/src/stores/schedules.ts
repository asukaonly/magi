import { create } from 'zustand';
import type { ScheduleDTO } from '@/api';

interface SchedulesState {
  schedules: ScheduleDTO[];
  runningCount: number;
  hydrate: (schedules: ScheduleDTO[]) => void;
  reset: () => void;
}

const countRunning = (schedules: ScheduleDTO[]): number =>
  schedules.reduce(
    (acc, s) => acc + (s.enabled && s.target_state?.running ? 1 : 0),
    0,
  );

export const useSchedulesStore = create<SchedulesState>((set) => ({
  schedules: [],
  runningCount: 0,
  hydrate: (schedules) =>
    set({ schedules, runningCount: countRunning(schedules) }),
  reset: () => set({ schedules: [], runningCount: 0 }),
}));
