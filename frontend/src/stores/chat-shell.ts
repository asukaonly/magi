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

const safeGetItem = (key: string): string | null => {
  try {
    if (typeof window === 'undefined' || !window.localStorage || typeof window.localStorage.getItem !== 'function') {
      return null;
    }
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
};

const safeSetItem = (key: string, value: string): void => {
  try {
    if (typeof window === 'undefined' || !window.localStorage || typeof window.localStorage.setItem !== 'function') {
      return;
    }
    window.localStorage.setItem(key, value);
  } catch {
    // ignore storage failures
  }
};

export const useChatShellStore = create<DesktopShellState>((set) => ({
  currentSessionId: null,
  sidebarCollapsed: safeGetItem('desktop-shell-sidebar-collapsed') === 'true',
  activePanel: 'none',
  setCurrentSessionId: (currentSessionId) => set({ currentSessionId }),
  setSidebarCollapsed: (sidebarCollapsed) => {
    safeSetItem('desktop-shell-sidebar-collapsed', String(sidebarCollapsed));
    set({ sidebarCollapsed });
  },
  toggleSidebarCollapsed: () =>
    set((state) => {
      const next = !state.sidebarCollapsed;
      safeSetItem('desktop-shell-sidebar-collapsed', String(next));
      return { sidebarCollapsed: next };
    }),
  setActivePanel: (activePanel) => set({ activePanel }),
  resetPanel: () => set({ activePanel: 'none' }),
}));
