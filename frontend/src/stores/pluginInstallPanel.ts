import { create } from 'zustand';

/**
 * Shared open/close state for the single mounted <PluginInstallPanel/>.
 *
 * MUST be a shared store (not per-component local state): the panel is mounted
 * ONCE in MainLayout but triggered from three independent entry points (the
 * first-run product tour, the empty-state sensor cards, and the chat
 * side-card). A store lets every entry point open the same panel without each
 * rendering its own dialog copy.
 *
 * `installMode` records whether the plugin still needs a registry install
 * before the connect flow can run (entry points decide this from the plugin's
 * installed/available state).
 */
interface PluginInstallPanelState {
  open: boolean;
  pluginId: string | null;
  installMode: boolean;
  openPanel: (pluginId: string, opts?: { install?: boolean }) => void;
  closePanel: () => void;
}

export const usePluginInstallPanelStore = create<PluginInstallPanelState>((set) => ({
  open: false,
  pluginId: null,
  installMode: false,
  openPanel: (pluginId, opts) =>
    set({ open: true, pluginId, installMode: opts?.install ?? false }),
  closePanel: () => set({ open: false, pluginId: null, installMode: false }),
}));
