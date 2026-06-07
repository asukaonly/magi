import { describe, expect, it, beforeEach } from 'vitest';
import { usePluginInstallPanelStore } from '../stores/pluginInstallPanel';

describe('pluginInstallPanel store', () => {
  beforeEach(() => usePluginInstallPanelStore.getState().closePanel());

  it('opens with pluginId + installMode and closes', () => {
    usePluginInstallPanelStore.getState().openPanel('photo-library', { install: true });
    let s = usePluginInstallPanelStore.getState();
    expect(s.open).toBe(true);
    expect(s.pluginId).toBe('photo-library');
    expect(s.installMode).toBe(true);
    usePluginInstallPanelStore.getState().closePanel();
    s = usePluginInstallPanelStore.getState();
    expect(s.open).toBe(false);
    expect(s.pluginId).toBeNull();
  });

  it('defaults installMode to false', () => {
    usePluginInstallPanelStore.getState().openPanel('calendar');
    expect(usePluginInstallPanelStore.getState().installMode).toBe(false);
  });

  it('carries an onDone callback and clears it on close', () => {
    const onDone = () => {};
    usePluginInstallPanelStore.getState().openPanel('photo-library', { onDone });
    expect(usePluginInstallPanelStore.getState().onDone).toBe(onDone);
    usePluginInstallPanelStore.getState().closePanel();
    expect(usePluginInstallPanelStore.getState().onDone).toBeNull();
  });
});
