import { create } from 'zustand';

export type ChatPanelType = 'settings' | 'personality' | 'memory' | 'none';

export interface DesktopShellState {
  currentSessionId: string | null;
  sidebarCollapsed: boolean;
  activePanel: ChatPanelType;
  setCurrentSessionId: (sessionId: string | null) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebarCollapsed: () => void;
  setActivePanel: (panel: ChatPanelType) => void;
  resetPanel: () => void;
}

export const useChatShellStore = create<DesktopShellState>((set) => ({
  currentSessionId: null,
  sidebarCollapsed: localStorage.getItem('desktop-shell-sidebar-collapsed') === 'true',
  activePanel: 'none',
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setSidebarCollapsed: (sidebarCollapsed) => {
    localStorage.setItem('desktop-shell-sidebar-collapsed', String(sidebarCollapsed));
    set({ sidebarCollapsed });
  },
  toggleSidebarCollapsed: () =>
    set((state) => {
      const next = !state.sidebarCollapsed;
      localStorage.setItem('desktop-shell-sidebar-collapsed', String(next));
      return { sidebarCollapsed: next };
    }),
  setActivePanel: (activePanel) => set({ activePanel }),
  resetPanel: () => set({ activePanel: 'none' }),
}));

