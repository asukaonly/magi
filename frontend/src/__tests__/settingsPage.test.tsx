import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SettingsPage } from '@/pages/Settings';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { memoryApi } from '@/api/modules/memory';
import { pluginsApi } from '@/api/modules/plugins';
import { timelineApi } from '@/api/modules/timeline';

vi.mock('@/components/config-forms/LLMForm', () => ({
  default: ({ value, onChange }: { value: any; onChange: (next: any) => void }) => (
    <button type="button" onClick={() => onChange({ ...value, model: 'gpt-5' })}>
      change-llm
    </button>
  ),
}));

vi.mock('@/components/config-forms/DynamicToolConfig', async () => {
  const actual = await vi.importActual<typeof import('@/components/config-forms/DynamicToolConfig')>(
    '@/components/config-forms/DynamicToolConfig'
  );
  return {
    ...actual,
    DynamicToolsConfig: () => <div>tools-config</div>,
  };
});

vi.mock('@/components/settings/LLMUsageSection', () => ({
  LLMUsageSection: () => <div>usage-section</div>,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
      update: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    listModels: vi.fn(),
    downloadModel: vi.fn(),
    getModelStatus: vi.fn(),
    clearAll: vi.fn(),
  },
}));

vi.mock('@/api/modules/timeline', () => ({
  timelineApi: {
    getSourceStatus: vi.fn(),
    requestSync: vi.fn(),
  },
}));

vi.mock('@/api/modules/plugins', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/plugins')>('@/api/modules/plugins');
  return {
    ...actual,
    pluginsApi: {
      ...actual.pluginsApi,
      list: vi.fn(),
      rescan: vi.fn(),
      enable: vi.fn(),
      disable: vi.fn(),
      reload: vi.fn(),
      updateSettings: vi.fn(),
    },
  };
});

const timelineSourceFixture = {
  source_name: 'browser_history',
  plugin_id: 'core-timeline',
  contribution_id: 'timeline.browser_history',
  display_name: 'Browser History',
  description: 'Visited URLs and optional page content snapshots.',
  fields: [
    {
      key: 'sensors.browser_history.enabled',
      type: 'switch',
      label: 'Enabled',
      description: 'Whether this source is active.',
      default: true,
      required: false,
      options: [],
      section: 'general',
      surface: 'timeline',
      order: 10,
    },
    {
      key: 'sensors.browser_history.sync_interval_minutes',
      type: 'number',
      label: 'Sync Interval (minutes)',
      description: 'Polling interval for interval-based sources.',
      default: 30,
      required: false,
      options: [],
      section: 'general',
      surface: 'timeline',
      order: 30,
    },
    {
      key: 'sensors.browser_history.fetch_page_content',
      type: 'switch',
      label: 'Fetch Page Content',
      description: 'Whether to include captured page content.',
      default: false,
      required: false,
      options: [],
      section: 'analysis',
      surface: 'timeline',
      order: 55,
    },
    {
      key: 'sensors.browser_history.edge_whitelist',
      type: 'tags',
      label: 'Edge Whitelist',
      description: 'Relationship edge types this source may write into the user graph.',
      default: ['VIEWED'],
      required: false,
      options: [],
      section: 'analysis',
      surface: 'timeline',
      order: 60,
    },
    {
      key: 'sensors.browser_history.source_path',
      type: 'path',
      label: 'Source Path',
      description: 'Optional local path or root directory for this source.',
      default: '',
      required: false,
      options: [],
      section: 'storage',
      surface: 'timeline',
      order: 45,
    },
  ],
  current_settings: {
    'sensors.browser_history.enabled': true,
    'sensors.browser_history.sync_interval_minutes': 30,
    'sensors.browser_history.fetch_page_content': false,
    'sensors.browser_history.edge_whitelist': ['VIEWED', 'VISITED', 'CARES_ABOUT', 'LIKES'],
    'sensors.browser_history.source_path': '/tmp/browser-history',
  },
  enabled: true,
  sync_mode: 'interval',
  sync_interval_minutes: 30,
  default_retention_mode: 'analyze_only',
  storage_mode: 'managed',
  source_path: '/tmp/browser-history',
  fetch_page_content: false,
  edge_whitelist: ['VIEWED', 'VISITED', 'CARES_ABOUT', 'LIKES'],
  supports_pull_sync: true,
  last_error: 'Permission denied',
  last_success: null,
  last_sync_at: '2026-03-11T09:00:00Z',
  next_run_at: '2026-03-11T09:30:00Z',
  scheduler_job_id: 'timeline-browser-history',
  runtime_base_dir: '/tmp/magi-runtime',
};

const chromeTimelineSourceFixture = {
  source_name: 'chrome_history',
  plugin_id: 'chrome-history',
  contribution_id: 'timeline.chrome_history',
  display_name: 'Chrome History',
  description: 'Local Google Chrome browsing history ingested into the user timeline.',
  fields: [
    {
      key: 'sensors.chrome_history.enabled',
      type: 'switch',
      label: 'Enabled',
      description: 'Whether this source is active.',
      default: false,
      required: false,
      options: [],
      section: 'general',
      surface: 'timeline',
      order: 10,
    },
    {
      key: 'sensors.chrome_history.sync_interval_minutes',
      type: 'number',
      label: 'Sync Interval (minutes)',
      description: 'Polling interval for interval-based sources.',
      default: 30,
      required: false,
      options: [],
      section: 'general',
      surface: 'timeline',
      order: 30,
    },
  ],
  current_settings: {
    'sensors.chrome_history.enabled': false,
    'sensors.chrome_history.sync_interval_minutes': 30,
    'sensors.chrome_history.initial_sync_configured': false,
    'sensors.chrome_history.initial_sync_policy': 'lookback_days',
    'sensors.chrome_history.initial_sync_lookback_days': 7,
  },
  enabled: false,
  sync_mode: 'manual',
  sync_interval_minutes: 30,
  default_retention_mode: 'analyze_only',
  storage_mode: 'managed',
  source_path: '',
  fetch_page_content: false,
  edge_whitelist: ['VISITED', 'VIEWED'],
  supports_pull_sync: true,
  activation_required: true,
  activation_flow: {
    title: 'Enable Chrome History',
    description: 'Choose how the first sync should seed the timeline.',
    confirm_label: 'Enable source',
    cancel_label: 'Not now',
    enabled_key: 'sensors.chrome_history.enabled',
    configured_key: 'sensors.chrome_history.initial_sync_configured',
    fields: [
      {
        key: 'sensors.chrome_history.initial_sync_policy',
        type: 'select',
        label: 'First Sync Scope',
        description: 'Decide how much history should be imported the first time.',
        default: 'lookback_days',
        required: false,
        options: [
          { label: 'Sync full history', value: 'full' },
          { label: 'Sync recent days', value: 'lookback_days' },
          { label: 'Only new records from now on', value: 'from_now' },
        ],
        section: 'activation',
        surface: 'timeline',
        order: 10,
      },
      {
        key: 'sensors.chrome_history.initial_sync_lookback_days',
        type: 'number',
        label: 'Recent Days',
        description: 'Used when the first-sync scope is set to recent days.',
        default: 7,
        required: false,
        options: [],
        section: 'activation',
        surface: 'timeline',
        order: 20,
        depends_on_key: 'sensors.chrome_history.initial_sync_policy',
        depends_on_values: ['lookback_days'],
      },
    ],
  },
  last_error: null,
  last_success: null,
  last_sync_at: null,
  next_run_at: null,
  scheduler_job_id: null,
  runtime_base_dir: '/tmp/magi-runtime',
};

const pluginsListFixture = {
  plugins: [
    {
      manifest: {
        plugin_id: 'core-tools',
        name: 'Core Tools',
        version: '1.0.0',
        description: 'Built-in tools',
        author: 'Magi Team',
        official: true,
        contribution_types: ['tool'],
        source: 'builtin',
        plugin_dir: '/tmp/plugins/core-tools',
        manifest_path: '/tmp/plugins/core-tools/plugin.toml',
      },
      enabled: true,
      trusted: true,
      loaded: true,
      healthy: true,
      last_error: null,
      current_settings: {},
      contributions: [
        {
          plugin_id: 'core-tools',
          contribution_id: 'weather',
          contribution_type: 'tool',
          display_name: 'weather',
          description: 'Built-in weather tool',
          surface: 'tools',
          fields: [],
          metadata: {},
        },
      ],
    },
    {
      manifest: {
        plugin_id: 'core-timeline',
        name: 'Core Timeline',
        version: '1.0.0',
        description: 'Built-in timeline sensors',
        author: 'Magi Team',
        official: true,
        contribution_types: ['sensor'],
        source: 'builtin',
        plugin_dir: '/tmp/plugins/core-timeline',
        manifest_path: '/tmp/plugins/core-timeline/plugin.toml',
      },
      enabled: true,
      trusted: true,
      loaded: true,
      healthy: true,
      last_error: null,
      current_settings: {
        sensors: {
          browser_history: {
            enabled: true,
          },
        },
      },
      contributions: [
        {
          plugin_id: 'core-timeline',
          contribution_id: 'timeline.browser_history',
          contribution_type: 'sensor',
          display_name: 'Browser History',
          description: 'Visited URLs and optional page content snapshots.',
          surface: 'timeline',
          fields: [],
          metadata: { domain: 'timeline' },
        },
      ],
    },
    {
      manifest: {
        plugin_id: 'core-actions',
        name: 'Core Actions',
        version: '1.0.0',
        description: 'Built-in actions',
        author: 'Magi Team',
        official: true,
        contribution_types: ['action'],
        source: 'builtin',
        plugin_dir: '/tmp/plugins/core-actions',
        manifest_path: '/tmp/plugins/core-actions/plugin.toml',
      },
      enabled: true,
      trusted: true,
      loaded: true,
      healthy: true,
      last_error: null,
      current_settings: {
        notifications: {
          default_level: 'info',
        },
        email: {
          default_sender: 'bot@example.com',
          provider_mode: 'simulated',
        },
      },
      contributions: [
        {
          plugin_id: 'core-actions',
          contribution_id: 'notify-user',
          contribution_type: 'action',
          display_name: 'Notify User',
          description: 'Send an in-app notification to the user.',
          surface: 'actions',
          fields: [
            {
              key: 'notifications.default_level',
              type: 'select',
              label: 'Default Notification Level',
              description: 'Default severity used for user notifications.',
              default: 'info',
              required: false,
              options: [
                { label: 'Info', value: 'info' },
                { label: 'Warning', value: 'warning' },
              ],
              section: 'notifications',
              surface: 'actions',
              order: 10,
            },
          ],
          metadata: {
            dangerous: false,
            required_permissions: [],
            tool_adapter_name: 'notify-user',
          },
        },
        {
          plugin_id: 'core-actions',
          contribution_id: 'send-email',
          contribution_type: 'action',
          display_name: 'Send Email',
          description: 'Send an outbound email through the configured action provider.',
          surface: 'actions',
          fields: [],
          metadata: {
            dangerous: false,
            required_permissions: [],
            tool_adapter_name: 'send-email',
          },
        },
      ],
    },
  ],
  total: 3,
};

describe('settings page save behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(configApi.get).mockResolvedValue({
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(configApi.update).mockResolvedValue({
      success: true,
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(memoryApi.listModels).mockResolvedValue({
      data: { models: [] },
    } as any);
    vi.mocked(timelineApi.getSourceStatus).mockResolvedValue({
      sources: [chromeTimelineSourceFixture, timelineSourceFixture],
    } as any);
    vi.mocked(timelineApi.requestSync).mockResolvedValue({
      queued: true,
      source_name: 'browser_history',
    } as any);
    vi.mocked(pluginsApi.list).mockResolvedValue(pluginsListFixture as any);
    vi.mocked(pluginsApi.rescan).mockResolvedValue(pluginsListFixture as any);
    vi.mocked(pluginsApi.enable).mockImplementation(async (pluginId: string) =>
      (pluginsListFixture.plugins.find((plugin) => plugin.manifest.plugin_id === pluginId) ?? pluginsListFixture.plugins[0]) as any
    );
    vi.mocked(pluginsApi.disable).mockImplementation(async (pluginId: string) => ({
      ...(pluginsListFixture.plugins.find((plugin) => plugin.manifest.plugin_id === pluginId) ?? pluginsListFixture.plugins[0]),
      enabled: false,
    }) as any);
    vi.mocked(pluginsApi.reload).mockImplementation(async (pluginId: string) =>
      (pluginsListFixture.plugins.find((plugin) => plugin.manifest.plugin_id === pluginId) ?? pluginsListFixture.plugins[0]) as any
    );
    vi.mocked(pluginsApi.updateSettings).mockImplementation(async (pluginId: string, updates: Record<string, any>) => ({
      ...(pluginsListFixture.plugins.find((plugin) => plugin.manifest.plugin_id === pluginId) ?? pluginsListFixture.plugins[0]),
      current_settings: updates,
    }) as any);
  });

  it('auto-saves non-llm settings after edits', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.system' }));

    const loopIntervalInput = screen.getAllByRole('spinbutton')[0];
    fireEvent.change(loopIntervalInput, { target: { value: '2' } });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    await waitFor(() => expect(configApi.update).toHaveBeenCalledTimes(1));
    expect(configApi.update).toHaveBeenCalledWith(
      expect.objectContaining({
        loop: expect.objectContaining({ interval: 2 }),
      })
    );
  });

  it('keeps llm changes local until the llm save button is clicked', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'change-llm' }));

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    expect(configApi.update).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.saveLLM' }));

    await waitFor(() => expect(configApi.update).toHaveBeenCalledTimes(1));
    expect(configApi.update).toHaveBeenCalledWith(
      expect.objectContaining({
        llm: expect.objectContaining({ model: 'gpt-5' }),
      })
    );
  });

  it('saves timeline source edits through plugins api', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.timeline' }));
    await screen.findByTestId('timeline-overview');
    await user.click(await screen.findByTestId('timeline-nav-source-browser_history'));

    const browserPanel = await screen.findByTestId('timeline-source-detail-browser_history');

    fireEvent.change(within(browserPanel).getByLabelText('Sync Interval (minutes)'), {
      target: { value: '45' },
    });
    await user.click(within(browserPanel).getByRole('switch', { name: 'Fetch Page Content' }));

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    });

    await waitFor(() => expect(pluginsApi.updateSettings).toHaveBeenCalled());
    expect(pluginsApi.updateSettings).toHaveBeenCalledWith(
      'core-timeline',
      expect.objectContaining({
        'sensors.browser_history.fetch_page_content': true,
      })
    );
  });

  it('shows expert-only edge controls and source status metadata', async () => {
    const user = userEvent.setup();
    const expertConfig = structuredClone(DEFAULT_SYSTEM_CONFIG);
    expertConfig.preferences.user_mode = 'expert';
    vi.mocked(configApi.get).mockResolvedValueOnce({
      data: expertConfig,
    } as any);

    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-browser_history'));

    const browserPanel = await screen.findByTestId('timeline-source-detail-browser_history');

    expect(await within(browserPanel).findAllByText('Permission denied')).toHaveLength(2);
    expect(within(browserPanel).getByLabelText('Edge Whitelist')).toHaveValue(
      'VIEWED, VISITED, CARES_ABOUT, LIKES'
    );
    expect(within(browserPanel).getByLabelText('Source Path')).toHaveValue(
      '/tmp/browser-history'
    );
  });

  it('opens activation flow before enabling chrome history', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    await user.click(
      within(chromePanel).getByRole('switch', { name: 'settings.timeline.fields.enabled' })
    );

    expect(await screen.findByText('Enable Chrome History')).toBeInTheDocument();
    expect(screen.getByLabelText('First Sync Scope')).toBeInTheDocument();
    expect(screen.getByLabelText('Recent Days')).toHaveValue(7);

    await user.click(screen.getByRole('button', { name: 'Enable source' }));

    await waitFor(() =>
      expect(pluginsApi.updateSettings).toHaveBeenCalledWith(
        'chrome-history',
        expect.objectContaining({
          'sensors.chrome_history.enabled': true,
          'sensors.chrome_history.initial_sync_configured': true,
          'sensors.chrome_history.initial_sync_policy': 'lookback_days',
          'sensors.chrome_history.initial_sync_lookback_days': 7,
        })
      )
    );
  });

  it('renders extensions page and can disable a plugin', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.extensions' }));

    expect(await screen.findByText('Core Tools')).toBeInTheDocument();
    expect(await screen.findByText('Core Timeline')).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'settings.extensions.actions.disable' })[0]);

    await waitFor(() => expect(pluginsApi.disable).toHaveBeenCalledWith('core-tools'));
  });

  it('renders actions page and reloads action plugins', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.actions' }));

    expect(await screen.findByText('Notify User')).toBeInTheDocument();
    expect(await screen.findByText('Send Email')).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'settings.extensions.actions.reload' })[0]);

    await waitFor(() => expect(pluginsApi.reload).toHaveBeenCalledWith('core-actions'));
  });
});
