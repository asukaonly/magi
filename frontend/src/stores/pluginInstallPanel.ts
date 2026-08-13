import { create } from 'zustand';

/**
 * Shared open/close state for the single mounted <PluginInstallPanel/>.
 *
 * MUST be a shared store (not per-component local state): the panel is mounted
 * ONCE in MainLayout but triggered from independent entry points such as the
 * first-run context prompt, history import, empty-state source cards, and the
 * chat side-card. A store lets every entry point open the same panel without
 * rendering its own dialog copy.
 *
 * `installMode` records whether the plugin still needs a registry install
 * before the connect flow can run (entry points decide this from the plugin's
 * installed/available state).
 */
export type PluginInstallPanelContext = 'default' | 'first_context' | 'history_import';

export interface PluginInstallDoneInfo {
  pluginId: string;
  sourceName?: string;
  firstContextCount?: number | null;
}

interface PluginInstallPanelState {
  open: boolean;
  pluginId: string | null;
  pluginName: string | null;
  pluginIcon: string | null;
  installMode: boolean;
  context: PluginInstallPanelContext;
  /**
   * Optional callback fired ONCE when the connect flow reaches its `done` phase
   * (enable + sync succeeded; memory may still be backfilling). Lets an entry
   * point react to a *successful* connect without owning the flow — e.g. the
   * NotificationCenter marks its suggestion acted-on only here, so a cancelled or
   * closed panel never drops the item. Cleared on close.
   */
  onDone: ((info?: PluginInstallDoneInfo) => void) | null;
  openPanel: (
    pluginId: string,
    opts?: {
      install?: boolean;
      pluginName?: string;
      pluginIcon?: string;
      onDone?: (info?: PluginInstallDoneInfo) => void;
      context?: PluginInstallPanelContext;
    },
  ) => void;
  closePanel: () => void;
}

export const usePluginInstallPanelStore = create<PluginInstallPanelState>((set) => ({
  open: false,
  pluginId: null,
  pluginName: null,
  pluginIcon: null,
  installMode: false,
  context: 'default',
  onDone: null,
  openPanel: (pluginId, opts) =>
    set({
      open: true,
      pluginId,
      pluginName: opts?.pluginName ?? null,
      pluginIcon: opts?.pluginIcon ?? null,
      installMode: opts?.install ?? false,
      context: opts?.context ?? 'default',
      onDone: opts?.onDone ?? null,
    }),
  closePanel: () =>
    set({
      open: false,
      pluginId: null,
      pluginName: null,
      pluginIcon: null,
      installMode: false,
      context: 'default',
      onDone: null,
    }),
}));
