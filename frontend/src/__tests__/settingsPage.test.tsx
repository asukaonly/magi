import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SettingsCenterDialog from '@/components/layout/SettingsCenterDialog';
import { SettingsPage } from '@/pages/Settings';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { pluginsApi } from '@/api/modules/plugins';
import { timelineApi } from '@/api/modules/timeline';
import { toolsApi } from '@/api/modules/tools';

const llmFormMock = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      if (params?.message) {
        return `${key}:${params.message}`;
      }
      return key;
    },
  }),
}));

vi.mock('@/i18n', () => ({
  default: {
    changeLanguage: vi.fn(),
  },
}));

vi.mock('@/components/config-forms/LLMForm', () => ({
  default: ({
    value,
    onChange,
    view,
    showAdvancedByDefault,
  }: {
    value: any;
    onChange: (next: any) => void;
    view?: 'all' | 'providers' | 'models';
    showAdvancedByDefault?: boolean;
  }) => (
    <div>
      {llmFormMock({ value, onChange, view, showAdvancedByDefault })}
      <div>{`llm-view:${view || 'all'}`}</div>
      <button type="button" onClick={() => onChange({ ...value, model: 'gpt-5' })}>
        change-llm
      </button>
    </div>
  ),
}));

vi.mock('@/pages/PersonalityModern', () => ({
  default: ({ embedded = false }: { embedded?: boolean }) => (
    <div>{`personality-modern:${embedded ? 'embedded' : 'standalone'}`}</div>
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

vi.mock('@/components/settings/LLMStatisticsSection', () => ({
  LLMStatisticsSection: () => <div data-testid="llm-statistics-section">llm-statistics-section</div>,
}));

vi.mock('@/components/settings/RuntimeStatisticsSection', () => ({
  RuntimeStatisticsSection: () => <div data-testid="runtime-statistics-section">runtime-statistics-section</div>,
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

vi.mock('@/api/modules/tools', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/tools')>('@/api/modules/tools');
  return {
    ...actual,
    toolsApi: {
      ...actual.toolsApi,
      listWithConfig: vi.fn(),
      updateToolConfig: vi.fn(),
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
  ],
  current_settings: {
    'sensors.browser_history.enabled': true,
    'sensors.browser_history.sync_interval_minutes': 30,
    'sensors.browser_history.fetch_page_content': false,
  },
  enabled: true,
  sync_mode: 'interval',
  sync_interval_minutes: 30,
  default_retention_mode: 'analyze_only',
  storage_mode: 'managed',
  source_path: '/tmp/browser-history',
  fetch_page_content: false,
  edge_whitelist: ['VIEWED', 'VISITED'],
  supports_pull_sync: true,
  running: false,
  last_run_at: '2026-03-11T08:58:00Z',
  last_result_count: 4,
  last_raw_result_count: 7,
  last_error: null,
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
  last_run_at: null,
  running: false,
  last_result_count: 0,
  last_raw_result_count: 0,
  next_run_at: null,
  scheduler_job_id: null,
  runtime_base_dir: '/tmp/magi-runtime',
};

const pluginsListFixture = {
  plugins: [
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
            sync_interval_minutes: 30,
            fetch_page_content: false,
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
        plugin_id: 'chrome-history',
        name: 'Chrome History',
        version: '1.0.0',
        description: 'Chrome history plugin',
        author: 'Magi Team',
        official: true,
        contribution_types: ['sensor'],
        source: 'builtin',
        plugin_dir: '/tmp/plugins/chrome-history',
        manifest_path: '/tmp/plugins/chrome-history/plugin.toml',
      },
      enabled: true,
      trusted: true,
      loaded: true,
      healthy: true,
      last_error: null,
      current_settings: {
        sensors: {
          chrome_history: {
            enabled: false,
            initial_sync_configured: false,
            initial_sync_policy: 'lookback_days',
            initial_sync_lookback_days: 7,
          },
        },
      },
      contributions: [
        {
          plugin_id: 'chrome-history',
          contribution_id: 'timeline.chrome_history',
          contribution_type: 'sensor',
          display_name: 'Chrome History',
          description: 'Local Google Chrome browsing history ingested into the user timeline.',
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
      ],
    },
  ],
  total: 3,
};

const toolsFixture = {
  tools: [
    {
      name: 'weather',
      display_name: 'Weather',
      description: 'Weather tool',
      category: 'builtin',
      version: '1.0.0',
      enabled: true,
      is_ready: true,
      is_multi_provider: false,
      providers: [],
      config_specs: [],
      current_values: {
        api_key: '',
      },
    },
  ],
  total: 1,
};

describe('settings page draft saving', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    llmFormMock.mockReset();

    vi.mocked(configApi.get).mockResolvedValue({
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(configApi.update).mockResolvedValue({
      success: true,
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
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
    vi.mocked(toolsApi.listWithConfig).mockResolvedValue(toolsFixture as any);
    vi.mocked(toolsApi.updateToolConfig).mockResolvedValue({
      success: true,
      message: 'ok',
    } as any);
  });

  it('keeps regular config changes local until save', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.language' }));
    await user.click(await screen.findByRole('button', { name: 'language.en' }));

    expect(configApi.update).not.toHaveBeenCalled();
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({ language: 'en' }),
        })
      )
    );
  });

  it('shows grouped memory navigation with dedicated sub-sections', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const memoryGroupButton = await screen.findByRole('button', { name: 'settings.tabs.memory' });

    expect(memoryGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryGeneral' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryWorkbench' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryEvents' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryKnowledge' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryReflection' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memorySkills' })).not.toBeInTheDocument();

    await user.click(memoryGroupButton);

    expect(memoryGroupButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryGeneral' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryWorkbench' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryEvents' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryKnowledge' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryReflection' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memorySkills' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'settings.tabs.memoryGeneral' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryKnowledge' }));
    expect(screen.getByRole('heading', { name: 'settings.tabs.memoryKnowledge' })).toBeInTheDocument();

    await user.click(memoryGroupButton);
    expect(memoryGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryGeneral' })).not.toBeInTheDocument();
  });

  it('saves split memory settings across general and knowledge sections', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    await user.click(screen.getByRole('switch', { name: 'settings.memory.fields.async_embeddings.label' }));

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryKnowledge' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryKnowledge' });
    const l2BatchIntervalInput = await screen.findByLabelText('settings.memory.fields.l2_batch_flush_interval_seconds.label');
    fireEvent.change(l2BatchIntervalInput, { target: { value: '90' } });
    await user.click(screen.getByRole('switch', { name: 'settings.memory.fields.enable_l2_conflict_arbitration.label' }));
    const arbitrationThresholdInput = await screen.findByLabelText(
      'settings.memory.fields.l2_conflict_arbitration_min_confidence.label'
    );
    fireEvent.change(arbitrationThresholdInput, { target: { value: '0.9' } });

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            async_embeddings: false,
            l2: expect.objectContaining({
              batch_flush_interval_seconds: 90,
              conflict_arbitration_enabled: false,
              conflict_arbitration_min_confidence: 0.9,
            }),
          }),
        })
      )
    );
  });

  it('shows grouped model configuration navigation with provider and model sub-sections', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const llmGroupButton = await screen.findByRole('button', { name: 'settings.tabs.llm' });

    expect(screen.getByText('settings.shellTitle')).toBeInTheDocument();
    expect(llmGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'settings.tabs.llmProviders' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.llmModels' })).not.toBeInTheDocument();

    await user.click(llmGroupButton);

    expect(llmGroupButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'settings.tabs.llmProviders' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.llmModels' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'settings.tabs.llmProviders' })).toBeInTheDocument();
    expect(screen.getByText('llm-view:providers')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.llmModels' }));
    expect(screen.getByRole('heading', { name: 'settings.tabs.llmModels' })).toBeInTheDocument();
    expect(screen.getByText('llm-view:models')).toBeInTheDocument();

    await user.click(llmGroupButton);
    expect(llmGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'settings.tabs.llmProviders' })).not.toBeInTheDocument();
  });

  it('allows collapsing the sensors navigation group after expanding it', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const sensorsGroupButton = await screen.findByRole('button', { name: 'settings.tabs.timeline' });

    expect(sensorsGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('timeline-nav-overview')).not.toBeInTheDocument();

    await user.click(sensorsGroupButton);

    expect(sensorsGroupButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('timeline-nav-overview')).toBeInTheDocument();

    await user.click(sensorsGroupButton);

    expect(sensorsGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('timeline-nav-overview')).not.toBeInTheDocument();
  });

  it('does not force advanced model settings open by default', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llmModels' }));

    await waitFor(() => {
      expect(llmFormMock).toHaveBeenCalledWith(
        expect.objectContaining({
          view: 'models',
          showAdvancedByDefault: undefined,
        })
      );
    });
  });

  it('keeps timeline source changes in draft until save', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await screen.findByTestId('timeline-overview');
    await user.click(await screen.findByTestId('timeline-nav-source-browser_history'));

    const browserPanel = await screen.findByTestId('timeline-source-detail-browser_history');

    fireEvent.change(within(browserPanel).getByLabelText('Sync Interval (minutes)'), {
      target: { value: '45' },
    });
    await user.click(within(browserPanel).getByRole('switch', { name: 'Fetch Page Content' }));

    expect(pluginsApi.updateSettings).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(pluginsApi.updateSettings).toHaveBeenCalledWith(
        'core-timeline',
        expect.objectContaining({
          'sensors.browser_history.sync_interval_minutes': 45,
          'sensors.browser_history.fetch_page_content': true,
        })
      )
    );
  });

  it('keeps activation flow results local until save', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    await user.click(within(chromePanel).getByRole('switch', { name: 'settings.timeline.fields.enabled' }));

    expect(await screen.findByText('Enable Chrome History')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Enable source' }));

    expect(pluginsApi.updateSettings).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(pluginsApi.updateSettings).toHaveBeenCalledWith(
        'chrome-history',
        expect.objectContaining({
          'sensors.chrome_history.enabled': true,
          'sensors.chrome_history.initial_sync_configured': true,
        })
      )
    );
  });

  it('discard restores draft values without saving', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.language' }));
    await user.click(await screen.findByRole('button', { name: 'language.en' }));
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.actions.discard' }));

    expect(configApi.update).not.toHaveBeenCalled();
    expect(screen.getByText('settings.allChangesSaved')).toBeInTheDocument();
  });

  it('hides sync controls for inactive timeline sources', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    expect(
      within(chromePanel).queryByRole('button', { name: 'settings.timeline.actions.syncNow' })
    ).not.toBeInTheDocument();
    expect(
      within(chromePanel).queryByRole('button', { name: 'settings.timeline.actions.refresh' })
    ).not.toBeInTheDocument();
  });

  it('prompts before closing when there are unsaved changes', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(<SettingsCenterDialog open onOpenChange={onOpenChange} />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.language' }));
    await user.click(await screen.findByRole('button', { name: 'language.en' }));

    await user.click(screen.getByRole('button', { name: 'settings.actions.close' }));

    expect(await screen.findByText('settings.closeConfirm.title')).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);

    await user.click(screen.getByRole('button', { name: 'settings.closeConfirm.confirm' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it('allows changing a select field inside the settings dialog', async () => {
    const user = userEvent.setup();

    render(<SettingsCenterDialog open onOpenChange={vi.fn()} />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.language' }));
    await user.click(await screen.findByRole('button', { name: 'language.en' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeEnabled());
  });

  it('renders the personality editor inside settings', async () => {
    const user = userEvent.setup();

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.personality' }));

    expect(await screen.findByText('personality-modern:embedded')).toBeInTheDocument();
    expect(screen.getByTestId('settings-section-content')).not.toHaveClass('max-w-3xl');
    expect(screen.queryByRole('button', { name: 'settings.actions.save' })).not.toBeInTheDocument();
  });

  it('applies the dedicated warm settings theme shell to the settings workspace', async () => {
    render(<SettingsPage />);

    const settingsRoot = await screen.findByTestId('settings-theme-root');
    const activeNav = screen.getByRole('button', { name: 'settings.tabs.preferences' });

    expect(settingsRoot.className).toContain('settings-theme-surface');
    expect(activeNav.className).toContain('var(--settings-nav-active)');
  });

  it('does not expose the system settings entry in user-facing navigation', async () => {
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });

    expect(screen.queryByRole('button', { name: 'settings.tabs.system' })).not.toBeInTheDocument();
  });

  it('shows grouped statistics navigation with dedicated sub-sections', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const statisticsGroupButton = await screen.findByRole('button', { name: 'settings.tabs.statistics' });

    expect(statisticsGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'settings.tabs.statisticsLlm' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.statisticsRuntime' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.usage' })).not.toBeInTheDocument();

    await user.click(statisticsGroupButton);

    expect(statisticsGroupButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'settings.tabs.statisticsLlm' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.statisticsRuntime' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'settings.tabs.statisticsLlm' })).toBeInTheDocument();
    expect(screen.getByTestId('llm-statistics-section')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.statisticsRuntime' }));

    expect(screen.getByRole('heading', { name: 'settings.tabs.statisticsRuntime' })).toBeInTheDocument();
    expect(screen.getByTestId('runtime-statistics-section')).toBeInTheDocument();
    expect(screen.getByTestId('settings-section-content')).not.toHaveClass('max-w-3xl');
  });

  it('renders the top-level settings navigation in the user-facing order with sensors renamed', async () => {
    render(<SettingsPage />);

    const nav = (await screen.findByRole('button', { name: 'settings.tabs.preferences' })).closest('nav');
    expect(nav).toBeTruthy();

    const topLevelButtons = within(nav as HTMLElement)
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label'))
      .filter((label): label is string => Boolean(label))
      .filter((label) =>
        [
          'settings.tabs.preferences',
          'settings.tabs.llm',
          'settings.tabs.personality',
          'settings.tabs.memory',
          'settings.tabs.extensions',
          'settings.tabs.timeline',
          'settings.tabs.actions',
          'settings.tabs.tools',
          'settings.tabs.statistics',
        ].includes(label)
      );

    expect(topLevelButtons).toEqual([
      'settings.tabs.preferences',
      'settings.tabs.llm',
      'settings.tabs.personality',
      'settings.tabs.memory',
      'settings.tabs.extensions',
      'settings.tabs.timeline',
      'settings.tabs.actions',
      'settings.tabs.tools',
      'settings.tabs.statistics',
    ]);
  });
});
