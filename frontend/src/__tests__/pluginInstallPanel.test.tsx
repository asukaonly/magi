import { render, screen, waitFor } from '@testing-library/react';
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
    } as any);

    const onDone = vi.fn();
    render(<PluginInstallPanel />);
    usePluginInstallPanelStore.getState().openPanel('calendar', { onDone });

    // The flow polls /sensors/status once at SYNC_POLL_MS (1500ms) before the
    // sync step completes, so allow generous headroom over the default 5s.
    // `readyTitle` shows twice in the done state (the memory step label + the
    // standalone "✓ now I get you" line), so match all + assert the terminal
    // "Done" close button (only rendered once the flow settles).
    await waitFor(
      () => {
        expect(screen.getAllByText(/pluginInstallPanel\.readyTitle/).length).toBeGreaterThan(0);
        expect(
          screen.getByRole('button', { name: 'pluginInstallPanel.close' }),
        ).toBeInTheDocument();
      },
      { timeout: 8000 },
    );

    // onDone fires exactly once when the flow reaches `done`.
    expect(onDone).toHaveBeenCalledTimes(1);
  }, 12000);

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
