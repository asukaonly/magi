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
  moodDays: TimelineMoodCalendarDay[];
  standoutItems: TimelineStandoutItem[];
  onSelectDate: ((isoDate: string) => void) | null;
  onSelectStandoutEpisode: ((episodeId: string) => void) | null;
  // Toolbar bits — used by AppTitleBar
  scale: 'month' | 'week' | 'day' | 'hour';
  dateLabel: string;
  draftQuery: string;
  canGoNext: boolean;
  onScaleChange: ((next: 'month' | 'week' | 'day' | 'hour') => void) | null;
  onPrevious: (() => void) | null;
  onNext: (() => void) | null;
  onDraftQueryChange: ((next: string) => void) | null;
  onSubmitQuery: (() => void) | null;
  onRefresh: (() => void) | null;
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
}

const DEFAULT_TIMELINE_PANEL: TimelinePanelState = {
  monthForCalendar: '',
  selectedDate: '',
  moodDays: [],
  standoutItems: [],
  onSelectDate: null,
  onSelectStandoutEpisode: null,
  scale: 'day',
  dateLabel: '',
  draftQuery: '',
  canGoNext: false,
  onScaleChange: null,
  onPrevious: null,
  onNext: null,
  onDraftQueryChange: null,
  onSubmitQuery: null,
  onRefresh: null,
};

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
}));
