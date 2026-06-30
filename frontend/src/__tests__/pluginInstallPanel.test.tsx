import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { sensorsApi } from '../api/modules/sensors';
import { pluginsApi } from '../api/modules/plugins';
import { usePluginInstallPanelStore } from '../stores/pluginInstallPanel';
import { PluginInstallPanel } from '../components/plugins/PluginInstallPanel';

// Mirror the repo convention (see systemSuggestionSideCard.test.tsx): t() echoes
// the key, so assertions target the i18n key strings rather than translations.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }),
}));

describe('PluginInstallPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    usePluginInstallPanelStore.getState().closePanel();
  });

  it('renders nothing while the store is closed', () => {
    const { container } = render(<PluginInstallPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it('runs a zero-config flow to a done state', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 's',
            plugin_id: 'calendar',
            activation_flow: {
              enabled_key: 'sensors.s.enabled',
              configured_key: 'sensors.s.configured',
              fields: [],
              authorize_on_confirm: false,
            },
            last_success: null,
            last_result_count: 0,
          },
        ],
      } as any)
      .mockResolvedValue({
        sources: [
          { source_name: 's', plugin_id: 'calendar', last_success: 'x', last_result_count: 9 },
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 9,
      l2_ready: true,
      l2_total_count: 9,
      l2_processed_count: 9,
      l2_remaining_count: 0,
    } as any);

    let pluginsChangedFired = false;
    const onPluginsChanged = () => { pluginsChangedFired = true; };
    window.addEventListener('magi-plugins-changed', onPluginsChanged);

    const onDone = vi.fn();
    render(<PluginInstallPanel />);
    usePluginInstallPanelStore.getState().openPanel('calendar', { onDone });

    // The flow polls /sensors/status once at SYNC_POLL_MS (1500ms) before the
    // sync step completes, so allow generous headroom over the default 5s. The
    // memory step now shows the organized-progress detail; assert it plus the
    // terminal "Done" close button (only rendered once the flow settles).
    await waitFor(
      () => {
        expect(screen.getAllByText(/pluginInstallPanel\.memoryProgress/).length).toBeGreaterThan(0);
        expect(
          screen.getByRole('button', { name: 'pluginInstallPanel.close' }),
        ).toBeInTheDocument();
      },
      { timeout: 8000 },
    );

    // onDone fires exactly once when the flow reaches `done`.
    expect(onDone).toHaveBeenCalledTimes(1);
    // A completed connect flow broadcasts PLUGINS_CHANGED so suggestion surfaces refresh.
    expect(pluginsChangedFired).toBe(true);
    window.removeEventListener('magi-plugins-changed', onPluginsChanged);
  }, 12000);

  it('shows the capability consent before installing in install mode', async () => {
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      plugins: [
        {
          plugin_id: 'netease-music',
          name: 'NetEase',
          name_i18n: {},
          version: '0.1.2',
          official: true,
          capabilities: [{ capability: 'network', scope: ['ws.audioscrobbler.com'] }],
        },
      ],
      registry_version: '2',
    } as any);
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);
    // After install the flow fetches status; no activation flow → it short-circuits.
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({
      sources: [{ source_name: 's', plugin_id: 'netease-music', activation_flow: null }],
    } as any);

    render(<PluginInstallPanel />);
    usePluginInstallPanelStore.getState().openPanel('netease-music', { install: true });

    // Consent dialog appears and nothing is installed yet.
    await waitFor(() =>
      expect(
        screen.getByText(/settings\.marketplace\.consent\.title\.install/),
      ).toBeInTheDocument(),
    );
    expect(installSpy).not.toHaveBeenCalled();

    // Confirming consent proceeds to the install.
    fireEvent.click(
      screen.getByRole('button', { name: 'settings.marketplace.consent.confirm.install' }),
    );
    await waitFor(() =>
      expect(installSpy).toHaveBeenCalledWith('netease-music', expect.anything()),
    );
  });

  it('shows the unsupported message when the source has no activation flow', async () => {
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({
      sources: [{ source_name: 's', plugin_id: 'weixin', activation_flow: null }],
    } as any);

    render(<PluginInstallPanel />);
    usePluginInstallPanelStore.getState().openPanel('weixin');

    await waitFor(() =>
      expect(screen.getByText('pluginInstallPanel.unsupported')).toBeInTheDocument(),
    );
  });
});
