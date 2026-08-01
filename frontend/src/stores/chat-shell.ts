import { create } from 'zustand';
import type { TimelineMoodCalendarDay, TimelineStandoutItem } from '@/api/modules/timeline';

export type ChatPanelType = 'conversation' | 'settings' | 'memory' | 'timeline' | 'tasks' | 'none';

export interface SettingsNavigationIntent {
  section?: string | null;
  source?: string | null;
}

export interface TimelinePanelState {
  monthForCalendar: string;
  selectedDate: string;
  /** ISO YYYY-MM-DD of selection range start (inclusive). */
  selectedRangeStart: string;
  /** ISO YYYY-MM-DD of selection range end (inclusive). */
  selectedRangeEnd: string;
  moodDays: TimelineMoodCalendarDay[];
  standoutItems: TimelineStandoutItem[];
  onSelectDate: ((isoDate: string) => void) | null;
  onSelectStandoutEpisode: ((episodeId: string) => void) | null;
  // Toolbar bits — used by AppTitleBar
  scale: 'month' | 'week' | 'day' | 'hour';
  dateLabel: string;
  viewportStart: number; // unix seconds
  draftQuery: string;
  canGoNext: boolean;
  onScaleChange: ((next: 'month' | 'week' | 'day' | 'hour') => void) | null;
  onPrevious: (() => void) | null;
  onNext: (() => void) | null;
  onDraftQueryChange: ((next: string) => void) | null;
  onSubmitQuery: (() => void) | null;
  onSelectFromDateInput: ((value: string) => void) | null;
}

export interface DesktopShellState {
  currentSessionId: string | null;
  activePanel: ChatPanelType;
  settingsNavigationIntent: SettingsNavigationIntent | null;
  portraitRailOpen: boolean;
  viewportIsNarrow: boolean;
  timelinePanel: TimelinePanelState;
  setCurrentSessionId: (sessionId: string | null) => void;
  setActivePanel: (panel: ChatPanelType) => void;
  setSettingsNavigationIntent: (intent: SettingsNavigationIntent | null) => void;
  clearSettingsNavigationIntent: () => void;
  resetPanel: () => void;
  setPortraitRailOpen: (open: boolean) => void;
  setViewportIsNarrow: (narrow: boolean) => void;
  setTimelinePanel: (next: Partial<TimelinePanelState>) => void;
  resetContentState: () => void;
}

const padNumber = (value: number): string => String(value).padStart(2, '0');

const toUnixSeconds = (date: Date): number => Math.floor(date.getTime() / 1000);

const isoDateForLocalDate = (date: Date): string =>
  `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;

const monthKeyForLocalDate = (date: Date): string =>
  `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}`;

const latestCompleteDay = (): Date => {
  const now = new Date();
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  day.setDate(day.getDate() - 1);
  return day;
};

export const createDefaultTimelinePanel = (): TimelinePanelState => {
  const date = latestCompleteDay();
  const selectedDate = isoDateForLocalDate(date);

  return {
    monthForCalendar: monthKeyForLocalDate(date),
    selectedDate,
    selectedRangeStart: selectedDate,
    selectedRangeEnd: selectedDate,
    moodDays: [],
    standoutItems: [],
    onSelectDate: null,
    onSelectStandoutEpisode: null,
    scale: 'day',
    dateLabel: '',
    viewportStart: toUnixSeconds(date),
    draftQuery: '',
    canGoNext: false,
    onScaleChange: null,
    onPrevious: null,
    onNext: null,
    onDraftQueryChange: null,
    onSubmitQuery: null,
    onSelectFromDateInput: null,
  };
};

const DEFAULT_TIMELINE_PANEL: TimelinePanelState = createDefaultTimelinePanel();

export const useChatShellStore = create<DesktopShellState>((set) => ({
  currentSessionId: null,
  activePanel: 'none',
  settingsNavigationIntent: null,
  portraitRailOpen: false,
  viewportIsNarrow: false,
  timelinePanel: DEFAULT_TIMELINE_PANEL,
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setActivePanel: (activePanel) => set({ activePanel }),
  setSettingsNavigationIntent: (settingsNavigationIntent) => set({ settingsNavigationIntent }),
  clearSettingsNavigationIntent: () => set({ settingsNavigationIntent: null }),
  resetPanel: () => set({ activePanel: 'none', settingsNavigationIntent: null }),
  setPortraitRailOpen: (portraitRailOpen) => set({ portraitRailOpen }),
  setViewportIsNarrow: (viewportIsNarrow) => set({ viewportIsNarrow }),
  setTimelinePanel: (next) =>
    set((state) => ({ timelinePanel: { ...state.timelinePanel, ...next } })),
  resetContentState: () => set({
    currentSessionId: null,
    portraitRailOpen: false,
    timelinePanel: createDefaultTimelinePanel(),
  }),
}));
