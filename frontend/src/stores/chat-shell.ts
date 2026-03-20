import { create } from 'zustand';

export type ChatPanelType = 'conversation' | 'settings' | 'memory' | 'timeline' | 'none';

export interface DesktopShellState {
  currentSessionId: string | null;
  activePanel: ChatPanelType;
  setCurrentSessionId: (sessionId: string | null) => void;
  setActivePanel: (panel: ChatPanelType) => void;
  resetPanel: () => void;
}

export const useChatShellStore = create<DesktopShellState>((set) => ({
  currentSessionId: null,
  activePanel: 'none',
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setActivePanel: (activePanel) => set({ activePanel }),
  resetPanel: () => set({ activePanel: 'none' }),
}));
