import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
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
        expect(screen.getAllByText('pluginInstallPanel.readyTitle')).toHaveLength(2);
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

  it('disables the close button while memory is still importing', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 'agent_history',
            plugin_id: 'agent-history',
            activation_flow: {
              enabled_key: 'sensors.agent_history.enabled',
              configured_key: 'sensors.agent_history.configured',
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
          {
            source_name: 'agent_history',
            plugin_id: 'agent-history',
            last_success: 'x',
            last_result_count: 34,
          },
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'agent_history',
    } as any);
    let resolveReadiness: ((value: any) => void) | null = null;
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveReadiness = resolve;
        }) as any,
    );

    render(<PluginInstallPanel />);
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('agent-history');
    });

    await waitFor(
      () => {
        expect(screen.getByTestId('step-memory-status')).toHaveAttribute('data-status', 'running');
      },
      { timeout: 8000 },
    );
    expect(screen.getByRole('button', { name: 'pluginInstallPanel.close' })).toBeDisabled();

    await act(async () => {
      resolveReadiness?.({
        source_name: 'agent_history',
        l1_event_count: 34,
        l2_ready: true,
        l2_total_count: 34,
        l2_processed_count: 34,
        l2_remaining_count: 0,
      });
    });
    await waitFor(
      () => {
        expect(screen.getByRole('button', { name: 'pluginInstallPanel.close' })).not.toBeDisabled();
      },
      { timeout: 8000 },
    );
  }, 12000);

  it('clears the previous flow before opening another plugin', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            description: 'Chrome desc',
            activation_flow: {
              enabled_key: 'sensors.chrome_history.enabled',
              configured_key: 'sensors.chrome_history.configured',
              fields: [],
              authorize_on_confirm: false,
            },
            last_success: null,
            last_result_count: 0,
          },
        ],
      } as any)
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            description: 'Chrome desc',
            last_success: 'chrome-done',
            last_result_count: 9,
          },
        ],
      } as any)
      .mockResolvedValue({
        sources: [
          {
            source_name: 'agent_history',
            plugin_id: 'agent-history',
            description: 'Agent desc',
            activation_flow: {
              enabled_key: 'sensors.agent_history.enabled',
              configured_key: 'sensors.agent_history.configured',
              fields: [],
              authorize_on_confirm: false,
            },
            last_success: null,
            last_result_count: 0,
          },
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'chrome_history',
    } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 'chrome_history',
      l1_event_count: 9,
      l2_ready: true,
      l2_total_count: 9,
      l2_processed_count: 9,
      l2_remaining_count: 0,
    } as any);

    const firstDone = vi.fn();
    const secondDone = vi.fn();
    render(<PluginInstallPanel />);
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('chrome-history', { onDone: firstDone });
    });

    await waitFor(() => expect(firstDone).toHaveBeenCalledTimes(1), { timeout: 8000 });

    fireEvent.click(screen.getByRole('button', { name: 'pluginInstallPanel.close' }));
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('agent-history', {
        onDone: secondDone,
        pluginName: 'Agent History',
        pluginIcon: 'lucide:bot',
      });
    });

    expect(screen.getByText('Agent History')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-icon-fallback')).toBeInTheDocument();
    expect(secondDone).not.toHaveBeenCalled();
    expect(screen.queryByText('Chrome desc')).not.toBeInTheDocument();
    expect(screen.queryByText('pluginInstallPanel.readyTitle')).not.toBeInTheDocument();
  }, 12000);

  it('keeps first-context memory progress scoped to the latest sync count', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            activation_flow: {
              enabled_key: 'sensors.chrome_history.enabled',
              configured_key: 'sensors.chrome_history.configured',
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
          {
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            last_success: 'x',
            last_result_count: 12,
          },
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'chrome_history',
    } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 'chrome_history',
      l1_event_count: 122,
      l2_ready: true,
      l2_total_count: 122,
      l2_processed_count: 122,
      l2_remaining_count: 0,
    } as any);

    render(<PluginInstallPanel />);
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('chrome-history');
    });

    await waitFor(
      () => {
        expect(screen.getAllByText('pluginInstallPanel.memoryProgress').length).toBeGreaterThan(0);
        expect(
          screen.queryByText('pluginInstallPanel.memoryProgressWithSourceTotal'),
        ).not.toBeInTheDocument();
      },
      { timeout: 8000 },
    );
  }, 12000);

  it('uses first-context copy when onboarding only prepares initial context', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            activation_flow: {
              enabled_key: 'sensors.chrome_history.enabled',
              configured_key: 'sensors.chrome_history.configured',
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
          {
            source_name: 'chrome_history',
            plugin_id: 'chrome-history',
            last_success: 'x',
            last_result_count: 125,
          },
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({
      queued: true,
      source_name: 'chrome_history',
    } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 'chrome_history',
      l1_event_count: 125,
      l2_ready: false,
      l2_total_count: 125,
      l2_processed_count: 101,
      l2_remaining_count: 24,
    } as any);

    const onDone = vi.fn();
    render(<PluginInstallPanel />);
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('chrome-history', {
        context: 'first_context',
        onDone,
      });
    });

    await waitFor(
      () => {
        expect(screen.getByText('pluginInstallPanel.firstContextDescription')).toBeInTheDocument();
        expect(screen.getAllByText('pluginInstallPanel.firstContextReadyTitle').length).toBeGreaterThan(0);
        expect(screen.getAllByText('pluginInstallPanel.firstContextPrepared').length).toBeGreaterThan(0);
        expect(screen.getByText('pluginInstallPanel.firstContextBackfillHint')).toBeInTheDocument();
        expect(screen.queryByText('pluginInstallPanel.stepMemory')).not.toBeInTheDocument();
        expect(screen.queryByText('pluginInstallPanel.memoryReadying')).not.toBeInTheDocument();
      },
      { timeout: 8000 },
    );
    expect(onDone).toHaveBeenCalledWith({
      pluginId: 'chrome-history',
      sourceName: 'chrome_history',
      firstContextCount: 125,
    });
  }, 12000);

  it('explains raw history reads that produce no new memory input', async () => {
    vi.spyOn(sensorsApi, 'getStatus')
      .mockResolvedValueOnce({
        sources: [
          {
            source_name: 's',
            plugin_id: 'chrome-history',
            activation_flow: {
              enabled_key: 'sensors.s.enabled',
              configured_key: 'sensors.s.configured',
              fields: [],
              authorize_on_confirm: false,
            },
            last_success: null,
            last_result_count: 0,
            last_raw_result_count: 0,
          },
        ],
      } as any)
      .mockResolvedValue({
        sources: [
          {
            source_name: 's',
            plugin_id: 'chrome-history',
            last_success: 'x',
            last_result_count: 0,
            last_raw_result_count: 7,
          },
        ],
      } as any);
    vi.spyOn(pluginsApi, 'updateSettings').mockResolvedValue({} as any);
    vi.spyOn(sensorsApi, 'requestSync').mockResolvedValue({ queued: true, source_name: 's' } as any);
    vi.spyOn(sensorsApi, 'getMemoryReadiness').mockResolvedValue({
      source_name: 's',
      l1_event_count: 0,
      l2_ready: false,
      l2_total_count: 0,
      l2_processed_count: 0,
      l2_remaining_count: 0,
    } as any);

    render(<PluginInstallPanel />);
    usePluginInstallPanelStore.getState().openPanel('chrome-history');

    await waitFor(
      () => {
        expect(screen.getAllByText('pluginInstallPanel.syncedRawOnly').length).toBeGreaterThan(0);
        expect(screen.getAllByText('pluginInstallPanel.memoryEmptyAfterRaw').length).toBeGreaterThan(0);
        expect(screen.getAllByText('pluginInstallPanel.memoryNoNewTitle').length).toBeGreaterThan(0);
        expect(screen.queryByText('pluginInstallPanel.memoryReadying')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'pluginInstallPanel.close' })).toBeInTheDocument();
      },
      { timeout: 8000 },
    );
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
          icon: 'brand:neteasecloudmusic',
          capabilities: [{ capability: 'network', scope: ['ws.audioscrobbler.com'] }],
        },
      ],
      registry_version: '4',
      install_fingerprint: 'fingerprint-2',
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
    expect(screen.getByTestId('plugin-icon-fallback')).toBeInTheDocument();
    expect(installSpy).not.toHaveBeenCalled();

    // Confirming consent proceeds to the install.
    fireEvent.click(
      screen.getByRole('button', { name: 'settings.marketplace.consent.confirm.install' }),
    );
    await waitFor(() =>
      expect(installSpy).toHaveBeenCalledWith(
        'netease-music',
        'fingerprint-2',
        expect.anything(),
      ),
    );
  });

  it('does not allow consent when the requested plugin is absent from the registry', async () => {
    vi.spyOn(pluginsApi, 'getRegistry').mockResolvedValue({
      plugins: [],
      registry_version: '4',
      install_fingerprint: 'fingerprint-for-other-plugins',
    } as any);
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);

    render(<PluginInstallPanel />);
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('missing-plugin', { install: true });
    });

    expect(
      await screen.findByText('app:settings.marketplace.empty'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'settings.marketplace.consent.confirm.install' }),
    ).toBeDisabled();

    fireEvent.click(
      screen.getByRole('button', { name: 'settings.marketplace.consent.confirm.install' }),
    );
    expect(installSpy).not.toHaveBeenCalled();
  });

  it('keeps consent disabled when the registry cannot be loaded', async () => {
    vi.spyOn(pluginsApi, 'getRegistry').mockRejectedValue(new Error('offline'));
    const installSpy = vi
      .spyOn(pluginsApi, 'installFromRegistryWithProgress')
      .mockResolvedValue({} as any);

    render(<PluginInstallPanel />);
    act(() => {
      usePluginInstallPanelStore.getState().openPanel('missing-plugin', { install: true });
    });

    expect(
      await screen.findByText('app:settings.marketplace.error'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'settings.marketplace.consent.confirm.install' }),
    ).toBeDisabled();
    expect(installSpy).not.toHaveBeenCalled();
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
