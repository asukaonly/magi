import { create } from 'zustand';

export type ChatPanelType = 'conversation' | 'settings' | 'memory' | 'timeline' | 'tasks' | 'none';

export interface SettingsNavigationIntent {
  section?: string | null;
  source?: string | null;
}

export interface DesktopShellState {
  currentSessionId: string | null;
  activePanel: ChatPanelType;
  settingsNavigationIntent: SettingsNavigationIntent | null;
  portraitRailOpen: boolean;
  viewportIsNarrow: boolean;
  setCurrentSessionId: (sessionId: string | null) => void;
  setActivePanel: (panel: ChatPanelType) => void;
  setSettingsNavigationIntent: (intent: SettingsNavigationIntent | null) => void;
  clearSettingsNavigationIntent: () => void;
  resetPanel: () => void;
  setPortraitRailOpen: (open: boolean) => void;
  setViewportIsNarrow: (narrow: boolean) => void;
}

export const useChatShellStore = create<DesktopShellState>((set) => ({
  currentSessionId: null,
  activePanel: 'none',
  settingsNavigationIntent: null,
  portraitRailOpen: true,
  viewportIsNarrow: false,
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setActivePanel: (activePanel) => set({ activePanel }),
  setSettingsNavigationIntent: (settingsNavigationIntent) => set({ settingsNavigationIntent }),
  clearSettingsNavigationIntent: () => set({ settingsNavigationIntent: null }),
  resetPanel: () => set({ activePanel: 'none', settingsNavigationIntent: null }),
  setPortraitRailOpen: (portraitRailOpen) => set({ portraitRailOpen }),
  setViewportIsNarrow: (viewportIsNarrow) => set({ viewportIsNarrow }),
}));
