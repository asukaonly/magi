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
  setCurrentSessionId: (sessionId: string | null) => void;
  setActivePanel: (panel: ChatPanelType) => void;
  setSettingsNavigationIntent: (intent: SettingsNavigationIntent | null) => void;
  clearSettingsNavigationIntent: () => void;
  resetPanel: () => void;
}

export const useChatShellStore = create<DesktopShellState>((set) => ({
  currentSessionId: null,
  activePanel: 'none',
  settingsNavigationIntent: null,
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setActivePanel: (activePanel) => set({ activePanel }),
  setSettingsNavigationIntent: (settingsNavigationIntent) => set({ settingsNavigationIntent }),
  clearSettingsNavigationIntent: () => set({ settingsNavigationIntent: null }),
  resetPanel: () => set({ activePanel: 'none', settingsNavigationIntent: null }),
}));
