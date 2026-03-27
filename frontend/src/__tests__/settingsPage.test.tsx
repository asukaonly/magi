import { useEffect } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SettingsCenterDialog from '@/components/layout/SettingsCenterDialog';
import { SettingsPage } from '@/pages/Settings';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { pluginsApi } from '@/api/modules/plugins';
import { timelineApi } from '@/api/modules/timeline';
import { toolsApi } from '@/api/modules/tools';

const { syncCloseToTrayPreferenceMock, pickDirectoryMock, llmFormAutoChangeRef } = vi.hoisted(() => ({
  syncCloseToTrayPreferenceMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  llmFormAutoChangeRef: {
    current: null as null | ((args: { value: any; view?: 'all' | 'providers' | 'models' }) => any | null),
  },
}));

const llmFormMock = vi.fn();
const translationMap: Record<string, string> = {
  'settings.tabs.photo_library': '照片库',
  'settings.tabs.chrome_history': 'Chrome 历史',
  'settings.timeline.sourceDesc.photo_library': '引用照片库或导出目录，并决定保留多少原始媒体信息。',
  'settings.plugins.chrome-history.description': '本地 Google Chrome 浏览历史接入时间线',
  'settings.plugins.chrome-history.fields.sensors.chrome_history.profile.label': '配置档案',
  'settings.plugins.chrome-history.fields.sensors.chrome_history.profile.description': '要读取的 Chrome 配置目录，例如 Default 或 Profile 1。',
  'settings.plugins.chrome-history.fields.sensors.chrome_history.sync_mode.label': '同步方式',
  'settings.plugins.chrome-history.fields.sensors.chrome_history.sync_interval_minutes.label': '定时间隔',
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      if (params?.message) {
        return `${key}:${params.message}`;
      }
      return translationMap[key] ?? key;
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
    onAutoNormalize,
    view,
    showAdvancedByDefault,
  }: {
    value: any;
    onChange: (next: any) => void;
    onAutoNormalize?: (next: any) => void;
    view?: 'all' | 'providers' | 'models';
    showAdvancedByDefault?: boolean;
  }) => {
    useEffect(() => {
      const nextValue = llmFormAutoChangeRef.current?.({ value, view });
      if (nextValue) {
        if (onAutoNormalize) {
          onAutoNormalize(nextValue);
          return;
        }
        onChange(nextValue);
      }
    }, [onAutoNormalize, onChange, value, view]);

    return (
      <div>
        {llmFormMock({ value, onChange, view, showAdvancedByDefault })}
        <div>{`llm-view:${view || 'all'}`}</div>
        {value?.normalized ? <div>llm-normalized</div> : null}
        <button type="button" onClick={() => onChange({ ...value, model: 'gpt-5' })}>
          change-llm
        </button>
      </div>
    );
  },
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

vi.mock('@/runtime/desktop', () => ({
  syncCloseToTrayPreference: syncCloseToTrayPreferenceMock,
  pickDirectory: pickDirectoryMock,
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
    requestAuthorization: vi.fn(),
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
      getSettingsResource: vi.fn(),
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
  source_name: 'photo_library',
  plugin_id: 'photo-library',
  contribution_id: 'timeline.photo_library',
  display_name: 'Photo Library',
  description: 'Photo assets referenced from a local library path.',
  fields: [
    {
      key: 'sensors.photo_library.enabled',
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
      key: 'sensors.photo_library.sync_interval_minutes',
      type: 'number',
      label: 'Sync Interval (minutes)',
      description: 'Polling interval for interval-based sources.',
      default: 60,
      required: false,
      options: [],
      section: 'general',
      surface: 'timeline',
      order: 30,
    },
    {
      key: 'sensors.photo_library.source_path',
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
    'sensors.photo_library.enabled': true,
    'sensors.photo_library.sync_interval_minutes': 60,
    'sensors.photo_library.source_path': '/tmp/photo-library',
  },
  enabled: true,
  sync_mode: 'interval',
  sync_interval_minutes: 60,
  default_retention_mode: 'retain_raw',
  storage_mode: 'external_reference',
  source_path: '/tmp/photo-library',
  fetch_page_content: false,
  edge_whitelist: ['CAPTURED', 'RELATED_TO'],
  supports_pull_sync: false,
  running: false,
  last_run_at: '2026-03-11T08:58:00Z',
  last_result_count: 4,
  last_raw_result_count: 7,
  last_error: null,
  last_success: null,
  last_sync_at: '2026-03-11T09:00:00Z',
  next_run_at: '2026-03-11T09:30:00Z',
  scheduler_job_id: 'timeline-photo-library',
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
      depends_on_key: 'sensors.chrome_history.sync_mode',
      depends_on_values: ['interval'],
    },
  ],
  current_settings: {
    'sensors.chrome_history.enabled': false,
    'sensors.chrome_history.sync_mode': 'manual',
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
        plugin_id: 'photo-library',
        name: 'Photo Library',
        version: '1.0.0',
        description: 'Photo library plugin',
        author: 'Magi Team',
        official: true,
        contribution_types: ['sensor'],
        source: 'builtin',
        plugin_dir: '/tmp/plugins/photo-library',
        manifest_path: '/tmp/plugins/photo-library/plugin.toml',
      },
      enabled: true,
      trusted: true,
      loaded: true,
      healthy: true,
      last_error: null,
      current_settings: {
        sensors: {
          photo_library: {
            enabled: true,
            sync_interval_minutes: 60,
            source_path: '/tmp/photo-library',
          },
        },
      },
      contributions: [
        {
          plugin_id: 'photo-library',
          contribution_id: 'timeline.photo_library',
          contribution_type: 'sensor',
          display_name: 'Photo Library',
          description: 'Photo assets referenced from a local library path.',
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
        email: {
          default_sender: '',
          provider_mode: 'simulated',
        },
      },
      contributions: [
        {
          plugin_id: 'core-actions',
          contribution_id: 'send-email',
          contribution_type: 'action',
          display_name: 'Send Email',
          description: 'Send an outbound email through the configured action provider.',
          surface: 'actions',
          fields: [
            {
              key: 'email.default_sender',
              type: 'input',
              label: 'Default Sender',
              description: 'Default sender address for email actions.',
              default: '',
              required: false,
              options: [],
              section: 'email',
              surface: 'actions',
              order: 10,
            },
            {
              key: 'email.provider_mode',
              type: 'select',
              label: 'Delivery Mode',
              description: 'How email delivery is performed.',
              default: 'simulated',
              required: false,
              options: [
                { label: 'Simulated', value: 'simulated' },
              ],
              section: 'email',
              surface: 'actions',
              order: 20,
            },
          ],
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
    llmFormAutoChangeRef.current = null;
    syncCloseToTrayPreferenceMock.mockReset();
    pickDirectoryMock.mockReset();
    pickDirectoryMock.mockResolvedValue(undefined);

    vi.mocked(configApi.get).mockResolvedValue({
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(configApi.update).mockImplementation(async (nextConfig: any) => ({
      success: true,
      data: structuredClone(nextConfig),
    }) as any);
    vi.mocked(timelineApi.getSourceStatus).mockResolvedValue({
      sources: [chromeTimelineSourceFixture, timelineSourceFixture],
    } as any);
    vi.mocked(timelineApi.requestSync).mockResolvedValue({
      queued: true,
      source_name: 'photo_library',
    } as any);
    vi.mocked(timelineApi.requestAuthorization).mockResolvedValue({
      authorized: true,
      granted_types: ['steps'],
      denied_types: [],
      requested_types: ['steps'],
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

  it('renders the close-to-tray preference as enabled by default and saves changes', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const closeToTraySwitch = await screen.findByRole('switch', { name: 'settings.fields.closeToTray' });
    expect(closeToTraySwitch).toHaveAttribute('data-state', 'checked');

    await user.click(closeToTraySwitch);
    expect(closeToTraySwitch).toHaveAttribute('data-state', 'unchecked');

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({ close_to_tray_enabled: false }),
        })
      )
    );
    expect(syncCloseToTrayPreferenceMock).toHaveBeenCalledWith(false);
  });

  it('uses a full-width preferences pane without repeating single-field labels', async () => {
    render(<SettingsPage />);

    const content = await screen.findByTestId('settings-section-content');

    expect(content).not.toHaveClass('max-w-3xl');
    expect(screen.getAllByText('settings.fields.language')).toHaveLength(1);
    expect(screen.getAllByText('settings.fields.theme')).toHaveLength(1);
    expect(screen.getAllByText('settings.fields.closeToTray')).toHaveLength(1);
    expect(screen.queryByText('settings.fields.defaultChatWorkspace')).not.toBeInTheDocument();
  });

  it('renders the theme preference as a dropdown-style field', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const themeTrigger = await screen.findByRole('button', { name: 'settings.fields.theme' });

    expect(screen.queryByRole('button', { name: 'settings.theme.light' })).not.toBeInTheDocument();

    await user.click(themeTrigger);

    expect(await screen.findByRole('button', { name: 'settings.theme.light' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.theme.dark' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.theme.system' })).toBeInTheDocument();
  });

  it('does not mark provider settings dirty when llm form normalizes mounted values', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        llm: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm),
          providers: {
            openai: {
              ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.providers.openai),
              display_name: '',
            },
          },
        },
      },
    } as any);

    let consumed = false;
    llmFormAutoChangeRef.current = ({ value, view }) => {
      if (consumed || view !== 'providers') {
        return null;
      }
      consumed = true;
      return {
        ...value,
        providers: {
          ...value.providers,
          openai: {
            ...value.providers.openai,
            display_name: 'OpenAI',
          },
        },
      };
    };

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llmProviders' }));

    await screen.findByText('llm-view:providers');

    await waitFor(() => {
      expect(screen.queryByText('settings.pendingChanges')).not.toBeInTheDocument();
    });
    expect(screen.getByText('settings.allChangesSaved')).toBeInTheDocument();
  });

  it('keeps llm edits dirty when a later normalization pass refines the draft', async () => {
    const user = userEvent.setup();

    llmFormAutoChangeRef.current = ({ value, view }) => {
      if (view !== 'providers' || !value?.model || value.normalized) {
        return null;
      }

      return {
        ...value,
        normalized: true,
      };
    };

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llmProviders' }));
    await screen.findByText('llm-view:providers');

    await user.click(screen.getByRole('button', { name: 'change-llm' }));

    await waitFor(() => {
      expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeEnabled();
  });

  it('reloads llm settings from the saved server response after saving', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.update).mockResolvedValue({
      success: true,
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        llm: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm),
          normalized: true,
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llmProviders' }));
    await screen.findByText('llm-view:providers');

    await user.click(screen.getByRole('button', { name: 'change-llm' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() => {
      expect(screen.getByText('llm-normalized')).toBeInTheDocument();
    });
  });

  it('saves a picked default chat workspace path in conversation settings', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/Users/asuka/code/magi');
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));
    const workspaceInput = await screen.findByLabelText('settings.fields.defaultChatWorkspace');
    expect(workspaceInput).toHaveValue('~/.magi/chat-workspace');

    await user.click(screen.getByRole('button', { name: 'settings.actions.chooseDirectory' }));

    await waitFor(() => expect(pickDirectoryMock).toHaveBeenCalledTimes(1));
    expect(pickDirectoryMock).toHaveBeenCalledWith('~/.magi/chat-workspace');
    expect(workspaceInput).toHaveValue('/Users/asuka/code/magi');
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            default_chat_workspace_path: '/Users/asuka/code/magi',
          }),
        })
      )
    );
  });

  it('allows clearing the default chat workspace path before saving', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          default_chat_workspace_path: '/Users/asuka/code/magi',
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));
    const workspaceInput = await screen.findByLabelText('settings.fields.defaultChatWorkspace');
    expect(workspaceInput).toHaveValue('/Users/asuka/code/magi');

    await user.click(screen.getByRole('button', { name: 'settings.actions.clearDirectory' }));
    expect(workspaceInput).toHaveValue('');

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            default_chat_workspace_path: null,
          }),
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

  it('saves memory storage path from the general memory section alongside knowledge settings', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/Users/asuka/.magi/data/custom-memories');
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    await user.click(screen.getByRole('button', { name: 'settings.actions.chooseDirectory' }));

    await waitFor(() =>
      expect(pickDirectoryMock).toHaveBeenCalledWith('~/.magi/data/memories')
    );
    expect(
      screen.getByDisplayValue('/Users/asuka/.magi/data/custom-memories')
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('switch', { name: 'settings.memory.fields.async_embeddings.label' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'settings.memory.fields.embedding_backend.label' })
    ).not.toBeInTheDocument();

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
            db_path: '/Users/asuka/.magi/data/custom-memories',
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
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));

    const photoPanel = await screen.findByTestId('timeline-source-detail-photo_library');

    fireEvent.change(within(photoPanel).getByLabelText('Sync Interval (minutes)'), {
      target: { value: '75' },
    });
    await user.click(within(photoPanel).getByRole('switch', { name: 'settings.timeline.fields.enabled' }));

    expect(pluginsApi.updateSettings).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(pluginsApi.updateSettings).toHaveBeenCalledWith(
        'photo-library',
        expect.objectContaining({
          'sensors.photo_library.sync_interval_minutes': 75,
          'sensors.photo_library.enabled': false,
        })
      )
    );
  });

  it('uses translated timeline source labels in the nav and overview list', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await screen.findByTestId('timeline-overview');

    const photoNavItem = await screen.findByTestId('timeline-nav-source-photo_library');
    expect(within(photoNavItem).getByText('照片库')).toBeInTheDocument();
    expect(screen.getByText('引用照片库或导出目录，并决定保留多少原始媒体信息。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.timeline.actions.refresh' })).not.toBeInTheDocument();
  });

  it('keeps timeline nav items alphabetized after overview', async () => {
    const user = userEvent.setup();
    vi.mocked(timelineApi.getSourceStatus).mockResolvedValue({
      sources: [
        {
          ...timelineSourceFixture,
          source_name: 'gamma_source',
          contribution_id: 'timeline.gamma_source',
          display_name: 'Gamma',
          description: 'Gamma source',
          fields: [
            {
              ...timelineSourceFixture.fields[0],
              key: 'sensors.gamma_source.enabled',
            },
          ],
          current_settings: {
            'sensors.gamma_source.enabled': true,
          },
        },
        {
          ...timelineSourceFixture,
          source_name: 'alpha_source',
          contribution_id: 'timeline.alpha_source',
          display_name: 'Alpha',
          description: 'Alpha source',
          fields: [
            {
              ...timelineSourceFixture.fields[0],
              key: 'sensors.alpha_source.enabled',
            },
          ],
          current_settings: {
            'sensors.alpha_source.enabled': true,
          },
        },
        {
          ...timelineSourceFixture,
          source_name: 'beta_source',
          contribution_id: 'timeline.beta_source',
          display_name: 'Beta',
          description: 'Beta source',
          fields: [
            {
              ...timelineSourceFixture.fields[0],
              key: 'sensors.beta_source.enabled',
            },
          ],
          current_settings: {
            'sensors.beta_source.enabled': true,
          },
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));

    const overview = await screen.findByTestId('timeline-nav-overview');
    const alpha = await screen.findByTestId('timeline-nav-source-alpha_source');
    const beta = await screen.findByTestId('timeline-nav-source-beta_source');
    const gamma = await screen.findByTestId('timeline-nav-source-gamma_source');

    expect(overview.compareDocumentPosition(alpha) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(alpha.compareDocumentPosition(beta) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(beta.compareDocumentPosition(gamma) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

  it('does not expose Apple Health in the timeline settings anymore', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));

    expect(screen.queryByTestId('timeline-nav-source-apple_health')).not.toBeInTheDocument();
    expect(screen.queryByText('Apple 健康')).not.toBeInTheDocument();
  });

  it('renders translated chrome history fields without the chrome data path control', async () => {
    const user = userEvent.setup();
    vi.mocked(timelineApi.getSourceStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          fields: [
            ...chromeTimelineSourceFixture.fields,
            {
              key: 'sensors.chrome_history.source_path',
              type: 'path',
              label: 'Chrome Data Path',
              description: 'Root directory that contains Chrome profiles.',
              default: '~/Library/Application Support/Google/Chrome',
              required: false,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 20,
            },
            {
              key: 'sensors.chrome_history.profile',
              type: 'input',
              label: 'Profile',
              description: 'Chrome profile directory to read, such as Default or Profile 1.',
              default: 'Default',
              required: false,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 30,
            },
            {
              key: 'sensors.chrome_history.sync_mode',
              type: 'select',
              label: 'Sync Mode',
              description: 'How Chrome history should be synchronized.',
              default: 'manual',
              required: false,
              options: [
                { label: 'Manual', value: 'manual' },
                { label: 'Interval', value: 'interval' },
              ],
              section: 'general',
              surface: 'timeline',
              order: 40,
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
              order: 50,
              depends_on_key: 'sensors.chrome_history.sync_mode',
              depends_on_values: ['interval'],
            },
          ],
          current_settings: {
            ...chromeTimelineSourceFixture.current_settings,
            'sensors.chrome_history.source_path': '~/Library/Application Support/Google/Chrome',
            'sensors.chrome_history.profile': 'Default',
            'sensors.chrome_history.sync_mode': 'manual',
            'sensors.chrome_history.sync_interval_minutes': 30,
          },
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    expect(within(chromePanel).getByText('Chrome 历史')).toBeInTheDocument();
    expect(within(chromePanel).getByText('配置档案')).toBeInTheDocument();
    expect(within(chromePanel).getByText('同步方式')).toBeInTheDocument();
    expect(within(chromePanel).queryByText('Chrome Data Path')).not.toBeInTheDocument();
    expect(within(chromePanel).queryByText('定时间隔')).not.toBeInTheDocument();
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

  it('keeps the dialog border on the outer frame and clips content in an inner shell', async () => {
    render(<SettingsCenterDialog open onOpenChange={vi.fn()} />);

    const dialog = await screen.findByRole('dialog');
    const innerShell = screen.getByTestId('settings-center-shell');

    expect(dialog.className).not.toContain('overflow-hidden');
    expect(innerShell.className).toContain('overflow-hidden');
    expect(innerShell.className).toContain('rounded-[inherit]');
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
          'settings.tabs.conversation',
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
      'settings.tabs.conversation',
      'settings.tabs.personality',
      'settings.tabs.memory',
      'settings.tabs.extensions',
      'settings.tabs.timeline',
      'settings.tabs.actions',
      'settings.tabs.tools',
      'settings.tabs.statistics',
    ]);
  });

  it('shows the conversation settings section between llm and personality', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const conversationButton = await screen.findByRole('button', { name: 'settings.tabs.conversation' });

    await user.click(conversationButton);

    expect(screen.getByRole('heading', { name: 'settings.tabs.conversation' })).toBeInTheDocument();
    expect(screen.getByLabelText('settings.fields.defaultChatWorkspace')).toBeInTheDocument();
  });

  it('keeps a small horizontal gutter so field borders are not clipped in scrolling sections', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));

    const content = screen.getByTestId('settings-section-content');

    expect(content.className).toContain('pl-1');
    expect(content.className).toContain('pr-2');
  });
});
