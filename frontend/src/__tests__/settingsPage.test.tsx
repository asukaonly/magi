import { useEffect } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import SettingsCenterDialog from '@/components/layout/SettingsCenterDialog';
import { SettingsPage } from '@/pages/Settings';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { getControlSettings, updateControlSettings } from '@/api/modules/control';
import memoryApi from '@/api/modules/memory';
import { memoryPortabilityApi } from '@/api/modules/memoryPortability';
import { pluginsApi } from '@/api/modules/plugins';
import { sensorsApi } from '@/api/modules/sensors';
import { skillsApi } from '@/api/modules/skills';
import { toolsApi } from '@/api/modules/tools';

const {
  syncCloseToTrayPreferenceMock,
  syncAutoStartPreferenceMock,
  syncStartMinimizedPreferenceMock,
  requestDesktopNotificationPermissionMock,
  syncDesktopNotificationPreferencesMock,
  pickDirectoryMock,
  pickMemoryBackupFileMock,
  openExternalUrlMock,
  changeLanguageMock,
  llmFormAutoChangeRef,
  translateMock,
} = vi.hoisted(() => ({
  syncCloseToTrayPreferenceMock: vi.fn(),
  syncAutoStartPreferenceMock: vi.fn(),
  syncStartMinimizedPreferenceMock: vi.fn(),
  requestDesktopNotificationPermissionMock: vi.fn(),
  syncDesktopNotificationPreferencesMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  pickMemoryBackupFileMock: vi.fn(),
  openExternalUrlMock: vi.fn(),
  changeLanguageMock: vi.fn(),
  llmFormAutoChangeRef: {
    current: null as null | ((args: { value: any; view?: 'all' | 'providers' | 'models' }) => any | null),
  },
  translateMock: (key: string, params?: Record<string, any>) => {
    if (params?.message) {
      return `${key}:${params.message}`;
    }
    let result = translationMap[key] ?? key;
    if (params) {
      for (const [name, value] of Object.entries(params)) {
        result = result.replace(`{{${name}}}`, String(value));
      }
    }
    return result;
  },
}));

const llmFormMock = vi.fn();
const translationMap: Record<string, string> = {
  'settings.tabs.photo_library': '照片库',
  'settings.tabs.chrome_history': 'Chrome 历史',
  'settings.timeline.sourceDesc.photo_library': '引用照片库或导出目录，并决定保留多少原始媒体信息。',
  'settings.timeline.actions.backfill': '补旧数据',
  'settings.timeline.statuses.retrying': '等待重试（已尝试 {{count}} 次）',
  'sourceBackfill.title': '补回历史',
  'sourceBackfill.description': '选择 {{source}} 要补回的范围。',
  'sourceBackfill.rangeLabel': '时间范围',
  'sourceBackfill.ranges.last7Days': '近 7 天',
  'sourceBackfill.ranges.last30Days': '近 30 天',
  'sourceBackfill.ranges.custom': '自定义',
  'sourceBackfill.ranges.full': '全部历史',
  'sourceBackfill.rangeDescriptions.last7Days': '快速补最近几天的内容。',
  'sourceBackfill.rangeDescriptions.last30Days': '默认范围，适合补近期活动。',
  'sourceBackfill.rangeDescriptions.custom': '选择明确的开始和结束日期。',
  'sourceBackfill.rangeDescriptions.full': '尽量补完整历史，可能需要更久。',
  'sourceBackfill.custom.title': '选择日期',
  'sourceBackfill.custom.start': '开始日期',
  'sourceBackfill.custom.end': '结束日期',
  'sourceBackfill.custom.errorRequired': '请选择开始和结束日期',
  'sourceBackfill.custom.errorOrder': '结束日期不能早于开始日期',
  'sourceBackfill.idempotencyNote': '重复记录会自动跳过。',
  'sourceBackfill.cancel': '取消',
  'sourceBackfill.submit': '开始补回',
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: translateMock,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/i18n', () => ({
  default: {
    changeLanguage: changeLanguageMock,
  },
}));

vi.mock('@/components/config-forms/LLMForm', () => ({
  default: function MockLLMForm({
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
  }) {
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

vi.mock('@/components/personality/PersonalityModern', () => ({
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
    DynamicToolsConfig: ({ tools }: { tools: Array<{ name: string; display_name: string }> }) => (
      <div>
        <div>tools-config</div>
        {tools.map((tool) => (
          <div key={tool.name}>{tool.display_name}</div>
        ))}
      </div>
    ),
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
  syncAutoStartPreference: syncAutoStartPreferenceMock,
  syncStartMinimizedPreference: syncStartMinimizedPreferenceMock,
  syncSkipQuitConfirmationPreference: vi.fn(),
  pickDirectory: pickDirectoryMock,
  pickMemoryBackupFile: pickMemoryBackupFileMock,
  openExternalUrl: openExternalUrlMock,
}));

vi.mock('@/runtime/desktop-notifications', () => ({
  requestDesktopNotificationPermission: requestDesktopNotificationPermissionMock,
  syncDesktopNotificationPreferences: syncDesktopNotificationPreferencesMock,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
      update: vi.fn(),
      embeddingPreflight: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/control', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/control')>('@/api/modules/control');
  return {
    ...actual,
    getControlSettings: vi.fn(),
    updateControlSettings: vi.fn(),
  };
});

vi.mock('@/api/modules/memory', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/memory')>('@/api/modules/memory');
  return {
    ...actual,
    default: {
      ...actual.default,
      getEmbeddingVectorStatus: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/memoryPortability', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/memoryPortability')>(
    '@/api/modules/memoryPortability',
  );
  return {
    ...actual,
    memoryPortabilityApi: {
      createBackup: vi.fn(),
      createExport: vi.fn(),
      inspectRestore: vi.fn(),
      confirmRestore: vi.fn(),
      discardRestoreCandidate: vi.fn(),
      getActiveOperation: vi.fn(),
      getLatestOperation: vi.fn(),
      getOperation: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/sensors', () => ({
  sensorsApi: {
    getStatus: vi.fn(),
    requestSync: vi.fn(),
    requestStateFlush: vi.fn(),
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
      reload: vi.fn(),
      getSettingsResource: vi.fn(),
      getRegistry: vi.fn(),
      installFromRegistryWithProgress: vi.fn(),
      listConnections: vi.fn(),
      getConnection: vi.fn(),
      updateConnection: vi.fn(),
      startSettingsAction: vi.fn(),
      pollSettingsAction: vi.fn(),
      cancelSettingsAction: vi.fn(),
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

vi.mock('@/api/modules/skills', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/skills')>('@/api/modules/skills');
  return {
    ...actual,
    skillsApi: {
      ...actual.skillsApi,
      list: vi.fn(),
    },
  };
});

const timelineSourceFixture = {
  connection_id: 'photo-account', connection_display_name: 'Photo Account', connection_revision: 4,
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
  storage_mode: 'external_reference',
  source_path: '/tmp/photo-library',
  fetch_page_content: false,
  edge_whitelist: ['CAPTURED', 'RELATED_TO'],
  supports_pull_sync: false,
  supports_state_flush: false,
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
  connection_id: 'chrome-account', connection_display_name: 'Chrome Account', connection_revision: 4,
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
  storage_mode: 'managed',
  source_path: '',
  fetch_page_content: false,
  edge_whitelist: ['VISITED', 'VIEWED'],
  supports_pull_sync: true,
  supports_state_flush: false,
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

const browserDisplayGroup = (memberLabel: string, memberOrder: number) => ({
  id: 'browser_history',
  name: 'Browser History',
  name_i18n: { 'zh-CN': '浏览器历史' },
  description: 'Manage browser history sources.',
  description_i18n: { 'zh-CN': '统一管理浏览器历史入口。' },
  icon: 'lucide:globe',
  order: 10,
  member_label: memberLabel,
  member_label_i18n: { 'zh-CN': memberLabel },
  member_order: memberOrder,
});

const browserRegistryEntry = (
  pluginId: string,
  name: string,
  memberLabel: string,
  memberOrder: number,
  installed = false,
) => ({
  plugin_id: pluginId,
  protocol_version: 2,
  execution_mode: 'trusted_process',
  settings_fields: [], settings_actions: [], settings_resources: [], settings_ui_blocks: [],
  name,
  name_i18n: { 'zh-CN': `${memberLabel} 浏览器历史` },
  version: '0.1.0',
  description: `Read local ${memberLabel} browsing history.`,
  description_i18n: { 'zh-CN': `读取本地 ${memberLabel} 浏览记录。` },
  author: 'Magi Team',
  icon: `brand:${memberLabel.toLowerCase()}`,
  display_group: browserDisplayGroup(memberLabel, memberOrder),
  official: true,
  data_locality: 'local_only',
  contribution_types: ['sensor'],
  platforms: [],
  min_sdk_version: '0.2.0',
  homepage: '',
  repository: '',
  path: pluginId,
  installed,
  installed_version: installed ? '0.1.0' : null,
  update_available: false,
  capabilities: [],
});

const pluginsListFixture = {
  plugins: [
    {
      manifest: {
        protocol_version: 2, min_sdk_version: '0.2.0', execution_mode: 'restricted_process',
        settings_fields: timelineSourceFixture.fields, settings_actions: [], settings_resources: [], settings_ui_blocks: [],
        plugin_id: 'photo-library',
        name: 'Photo Library',
        version: '1.0.0',
        description: 'Photo library plugin',
        author: 'Magi Team',
        official: true,
        contribution_types: ['sensor'],
        source: 'external',
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
        protocol_version: 2, min_sdk_version: '0.2.0', execution_mode: 'restricted_process',
        settings_fields: chromeTimelineSourceFixture.fields, settings_actions: [], settings_resources: [], settings_ui_blocks: [],
        plugin_id: 'chrome-history',
        name: 'Chrome History',
        version: '1.0.0',
        description: 'Chrome history plugin',
        author: 'Magi Team',
        official: true,
        contribution_types: ['sensor'],
        source: 'external',
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
  ],
  total: 2,
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
      config_specs: [
        {
          path: 'default_provider',
          type: 'string',
          description: 'Default weather provider',
          sensitive: false,
          read_only: false,
          required: true,
          enum: ['openmeteo', 'qweather'],
          is_template: false,
        },
      ],
      current_values: {
        default_provider: 'openmeteo',
      },
    },
    {
      name: 'web-search',
      display_name: 'Web Search',
      description: 'Web search tool',
      category: 'builtin',
      version: '1.0.0',
      enabled: true,
      is_ready: true,
      is_multi_provider: false,
      providers: [],
      config_specs: [],
      current_values: {
        query: '',
      },
    },
    {
      name: 'browser-automation',
      display_name: 'Browser Automation',
      description: 'Plugin-provided browser automation tool',
      category: 'external',
      version: '1.0.0',
      enabled: true,
      is_ready: true,
      is_multi_provider: false,
      providers: [],
      config_specs: [],
      current_values: {},
    },
  ],
  total: 3,
};

const skillsFixture = [
  {
    name: 'browser',
    description: 'Browser automation skill',
    user_invocable: true,
    tags: [],
    directory: '/tmp/browser',
  },
];

describe('settings page draft saving', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(XMLHttpRequest.prototype, 'open');
    llmFormMock.mockReset();
    llmFormAutoChangeRef.current = null;
    changeLanguageMock.mockResolvedValue(undefined);
    document.documentElement.lang = 'zh-CN';
    syncCloseToTrayPreferenceMock.mockReset();
    syncAutoStartPreferenceMock.mockReset();
    syncStartMinimizedPreferenceMock.mockReset();
    requestDesktopNotificationPermissionMock.mockResolvedValue(true);
    pickDirectoryMock.mockReset();
    pickDirectoryMock.mockResolvedValue(undefined);
    pickMemoryBackupFileMock.mockReset();
    pickMemoryBackupFileMock.mockResolvedValue(undefined);
    openExternalUrlMock.mockReset();
    openExternalUrlMock.mockResolvedValue(undefined);

    vi.mocked(configApi.get).mockResolvedValue({
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(configApi.update).mockImplementation(async (nextConfig: any) => ({
      success: true,
      data: structuredClone(nextConfig),
    }) as any);
    vi.mocked(getControlSettings).mockResolvedValue({
      permission_mode: 'high_only',
      plan_approval_required: false,
    });
    vi.mocked(updateControlSettings).mockImplementation(async (nextSettings) => ({
      permission_mode: nextSettings.permission_mode ?? 'high_only',
      plan_approval_required: nextSettings.plan_approval_required ?? false,
    }));
    vi.mocked(memoryApi.getEmbeddingVectorStatus).mockResolvedValue({
      ready_counts: {
        l1: 0,
        l2_entities: 0,
        l2_edges: 0,
        l3: 0,
        l4: 0,
      },
      ready_total: 0,
      active_identities: {
        l1: null,
        l2_entities: null,
        l2_edges: null,
        l3: null,
        l4: null,
      },
      latest_job: null,
    });
    vi.mocked(memoryPortabilityApi.getActiveOperation).mockResolvedValue(null);
    vi.mocked(memoryPortabilityApi.getLatestOperation).mockResolvedValue(null);
    vi.mocked(memoryPortabilityApi.discardRestoreCandidate).mockResolvedValue(undefined);
    vi.mocked(configApi.embeddingPreflight).mockResolvedValue({
      severity: 'none',
      requires_rebuild: false,
      ready_total: 0,
      warnings: [],
      current: null,
      proposed: null,
    } as any);
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [chromeTimelineSourceFixture, timelineSourceFixture],
    } as any);
    vi.mocked(sensorsApi.requestSync).mockResolvedValue({
      queued: true,
      source_name: 'photo_library',
    } as any);
    vi.mocked(sensorsApi.requestStateFlush).mockResolvedValue({
      queued: true,
      source_name: 'screen_time',
    } as any);
    vi.mocked(sensorsApi.requestAuthorization).mockResolvedValue({
      authorized: true,
      granted_types: ['steps'],
      denied_types: [],
      requested_types: ['steps'],
    } as any);
    vi.mocked(pluginsApi.list).mockResolvedValue(pluginsListFixture as any);
    vi.mocked(pluginsApi.getRegistry).mockResolvedValue({ plugins: [], total: 0 } as any);
    vi.mocked(pluginsApi.installFromRegistryWithProgress).mockResolvedValue({} as any);
    vi.mocked(pluginsApi.rescan).mockResolvedValue(pluginsListFixture as any);
    vi.mocked(pluginsApi.reload).mockImplementation(async (pluginId: string) =>
      (pluginsListFixture.plugins.find((plugin) => plugin.manifest.plugin_id === pluginId) ?? pluginsListFixture.plugins[0]) as any
    );
    vi.mocked(pluginsApi.listConnections).mockResolvedValue([]);
    vi.mocked(pluginsApi.getConnection).mockImplementation(async (pluginId, connectionId) => ({
      plugin_id: pluginId, connection_id: connectionId, display_name: 'Account', enabled: true,
      settings: {}, credential_refs: {}, readiness: [], revision: 4,
    }));
    vi.mocked(pluginsApi.updateConnection).mockImplementation(async (pluginId, connectionId, input) => ({
      plugin_id: pluginId, connection_id: connectionId, display_name: 'Account', enabled: input.enabled ?? true,
      settings: input.settings ?? {}, credential_refs: {}, readiness: [], revision: input.expected_revision + 1,
    }));
    vi.mocked(pluginsApi.startSettingsAction).mockResolvedValue({
      status: 'succeeded',
      message: 'connected',
      data: {},
      settings_updates: {},
    } as any);
    vi.mocked(pluginsApi.pollSettingsAction).mockResolvedValue({
      status: 'succeeded',
      message: 'connected',
      data: {},
      settings_updates: {},
    } as any);
    vi.mocked(pluginsApi.cancelSettingsAction).mockResolvedValue({
      status: 'cancelled',
      message: 'cancelled',
      data: {},
      settings_updates: {},
    } as any);
    vi.mocked(skillsApi.list).mockResolvedValue(skillsFixture as any);
    vi.mocked(toolsApi.listWithConfig).mockResolvedValue(toolsFixture as any);
    vi.mocked(toolsApi.updateToolConfig).mockResolvedValue({
      success: true,
      message: 'ok',
    } as any);
  });

  afterEach(() => {
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it('aligns the settings header and footer with the section body', async () => {
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });

    expect(screen.getByTestId('settings-main-header')).toHaveClass('px-5');
    expect(screen.getByTestId('settings-main-header')).not.toHaveClass('px-10');
    expect(screen.getByTestId('settings-main-footer')).toHaveClass('px-5');
    expect(screen.getByTestId('settings-main-footer')).not.toHaveClass('px-10');
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

  it('does not apply interface language before save', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.language' }));
    await user.click(await screen.findByRole('button', { name: 'language.en' }));

    expect(document.documentElement.lang).toBe('zh-CN');
    expect(changeLanguageMock).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeEnabled();
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();
  });

  it('keeps unsaved theme changes dirty without reloading config', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    expect(configApi.get).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'settings.fields.theme' }));
    await user.click(await screen.findByRole('button', { name: 'settings.theme.dark' }));

    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeEnabled();
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();
    expect(configApi.get).toHaveBeenCalledTimes(1);
  });

  it('requires an app dialog confirmation for strong embedding preflight warnings', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.embeddingPreflight).mockResolvedValue({
      severity: 'strong',
      requires_rebuild: true,
      ready_total: 42,
      warnings: [{ layer: 'l1' }],
      current: null,
      proposed: null,
    } as any);

    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.language' }));
    await user.click(await screen.findByRole('button', { name: 'language.en' }));

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    expect(await screen.findByText('settings.memory.vector.preflightStrongTitle')).toBeInTheDocument();
    expect(configApi.update).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.memory.vector.preflightStrongCancel' }));

    await waitFor(() =>
      expect(screen.queryByText('settings.memory.vector.preflightStrongTitle')).not.toBeInTheDocument()
    );
    expect(configApi.update).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));
    expect(await screen.findByText('settings.memory.vector.preflightStrongTitle')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'settings.memory.vector.preflightStrongSave' }));

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

    const closeToTraySwitch = await screen.findByRole('switch', { name: 'settings.closeToTrayLabel' });
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

  it('saves desktop notification preferences', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const notificationsSwitch = await screen.findByRole('switch', { name: 'settings.desktopNotificationsLabel' });
    const previewsSwitch = await screen.findByRole('switch', { name: 'settings.desktopNotificationPreviewsLabel' });

    expect(notificationsSwitch).toHaveAttribute('data-state', 'checked');
    expect(previewsSwitch).toHaveAttribute('data-state', 'checked');

    await user.click(notificationsSwitch);
    await user.click(previewsSwitch);
    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            desktop_notifications_enabled: false,
            desktop_notification_previews_enabled: false,
          }),
        })
      )
    );
    expect(requestDesktopNotificationPermissionMock).not.toHaveBeenCalled();
  });

  it('keeps full conversation diagnostics enabled by default and saves changes', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const diagnosticsSwitch = await screen.findByRole('switch', {
      name: 'settings.diagnostics.fullContentLoggingLabel',
    });
    expect(diagnosticsSwitch).toHaveAttribute('data-state', 'checked');

    await user.click(diagnosticsSwitch);
    expect(diagnosticsSwitch).toHaveAttribute('data-state', 'unchecked');
    expect(configApi.update).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          diagnostics: {
            full_content_logging_enabled: false,
          },
        })
      )
    );
  });

  it('restores the saved diagnostic logging preference', async () => {
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        diagnostics: {
          full_content_logging_enabled: false,
        },
      },
    } as any);

    render(<SettingsPage />);

    const diagnosticsSwitch = await screen.findByRole('switch', {
      name: 'settings.diagnostics.fullContentLoggingLabel',
    });
    expect(diagnosticsSwitch).toHaveAttribute('data-state', 'unchecked');
  });

  it('saves proxy credentials from network proxy settings', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    await user.click(screen.getByRole('button', { name: 'settings.fields.networkProxy' }));
    await user.click(await screen.findByRole('button', { name: 'HTTP' }));

    await user.clear(screen.getByLabelText('settings.fields.proxyHost'));
    await user.type(screen.getByLabelText('settings.fields.proxyHost'), 'proxy.example.test');
    await user.type(screen.getByLabelText('settings.fields.proxyUsername'), 'magi-user');
    await user.type(screen.getByLabelText('settings.fields.proxyPassword'), 'secret-pass');

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          network: expect.objectContaining({
            enabled: true,
            proxy_type: 'http',
            host: 'proxy.example.test',
            port: 7890,
            username: 'magi-user',
            password: 'secret-pass',
          }),
        })
      )
    );
  });

  it('defaults TUN fake-IP compatibility on and can disable it independently', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByRole('button', { name: 'settings.tabs.preferences' });
    const compatibilitySwitch = screen.getByRole('switch', {
      name: 'settings.fakeIpCompatibility',
    });
    expect(compatibilitySwitch).toHaveAttribute('data-state', 'checked');

    await user.click(compatibilitySwitch);
    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          tools: expect.objectContaining({
            builtIn: expect.objectContaining({
              webFetch: expect.objectContaining({
                allowRfc2544BenchmarkRange: false,
                allowPrivateNetworkFetch: false,
              }),
            }),
          }),
        })
      )
    );
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

  it('feeds saved llm responses back into the provider form after saving', async () => {
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
      expect(llmFormMock).toHaveBeenCalledWith(
        expect.objectContaining({
          value: expect.objectContaining({
            normalized: true,
          }),
        })
      );
    });
  });

  it('saves workspace and control preferences from conversation settings', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/tmp/magi-workspace');
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));
    const workspaceInput = await screen.findByLabelText('settings.fields.defaultChatWorkspace');
    const planApprovalSwitch = await screen.findByTestId('plan-approval-switch');
    expect(workspaceInput).toHaveValue('~/.magi/chat-workspace');
    expect(planApprovalSwitch).toHaveAttribute('data-state', 'unchecked');

    await user.click(screen.getByRole('button', { name: 'settings.actions.chooseDirectory' }));
    await user.click(planApprovalSwitch);

    await waitFor(() => expect(pickDirectoryMock).toHaveBeenCalledTimes(1));
    expect(pickDirectoryMock).toHaveBeenCalledWith('~/.magi/chat-workspace');
    expect(workspaceInput).toHaveValue('/tmp/magi-workspace');
    expect(planApprovalSwitch).toHaveAttribute('data-state', 'checked');
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            default_chat_workspace_path: '/tmp/magi-workspace',
          }),
        })
      )
    );
    expect(updateControlSettings).toHaveBeenCalledWith({
      permission_mode: 'high_only',
      plan_approval_required: true,
    });
  });

  it('restores the default chat workspace path before saving', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          default_chat_workspace_path: '/tmp/magi-workspace',
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));
    const workspaceInput = await screen.findByLabelText('settings.fields.defaultChatWorkspace');
    expect(workspaceInput).toHaveValue('/tmp/magi-workspace');

    await user.click(screen.getByRole('button', { name: 'settings.actions.restoreDefaultDirectory' }));
    expect(workspaceInput).toHaveValue('~/.magi/chat-workspace');

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            default_chat_workspace_path: '~/.magi/chat-workspace',
          }),
        })
      )
    );
  });

  it('saves the conversation rhythm switch in conversation settings', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          conversation_rhythm_enabled: true,
          conversation_rhythm_mode: 'natural',
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));
    const rhythmSwitch = await screen.findByRole('switch', { name: 'settings.fields.conversationRhythm' });
    expect(rhythmSwitch).toHaveAttribute('data-state', 'checked');

    await user.click(rhythmSwitch);
    expect(rhythmSwitch).toHaveAttribute('data-state', 'unchecked');
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            conversation_rhythm_enabled: false,
            conversation_rhythm_mode: 'off',
          }),
        })
      )
    );
  });

  it('shows conversation rhythm off when the enabled flag is false', async () => {
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          conversation_rhythm_enabled: false,
          conversation_rhythm_mode: 'natural',
        },
      },
    } as any);

    render(<SettingsPage />);

    await userEvent.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));
    const rhythmSwitch = await screen.findByRole('switch', { name: 'settings.fields.conversationRhythm' });
    expect(rhythmSwitch).toHaveAttribute('data-state', 'unchecked');
  });

  it('defaults media grounding on while still allowing users to turn it off without vision support', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));

    const mediaGroundingSwitch = await screen.findByRole('switch', { name: 'settings.fields.mediaGrounding' });
    expect(mediaGroundingSwitch).toBeEnabled();
    expect(mediaGroundingSwitch).toHaveAttribute('data-state', 'checked');
    expect(screen.getByText('settings.mediaGroundingUnavailable')).toBeInTheDocument();

    await user.click(mediaGroundingSwitch);
    expect(mediaGroundingSwitch).toHaveAttribute('data-state', 'unchecked');
  });

  it('still lets users turn off media grounding after switching to a non-vision core model', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        llm: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm),
          selections: {
            ...structuredClone(DEFAULT_SYSTEM_CONFIG.llm.selections),
            core: {
              provider_id: 'openai',
              model: 'gpt-5',
              capabilities: {
                vision: false,
              },
            },
          },
        },
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          allow_media_grounding_for_conversation: true,
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.conversation' }));

    const mediaGroundingSwitch = await screen.findByRole('switch', { name: 'settings.fields.mediaGrounding' });
    expect(mediaGroundingSwitch).toBeEnabled();
    expect(mediaGroundingSwitch).toHaveAttribute('data-state', 'checked');
    expect(screen.getByText('settings.mediaGroundingUnavailable')).toBeInTheDocument();

    await user.click(mediaGroundingSwitch);
    expect(mediaGroundingSwitch).toHaveAttribute('data-state', 'unchecked');
    expect(screen.getByText('settings.pendingChanges')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          preferences: expect.objectContaining({
            allow_media_grounding_for_conversation: false,
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
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryData' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryWorkbench' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryEvents' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryKnowledge' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryReflection' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memorySkills' })).not.toBeInTheDocument();

    await user.click(memoryGroupButton);

    expect(memoryGroupButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryGeneral' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryData' })).toBeInTheDocument();
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

  it('places memory data management after vector maintenance and before danger on the data page without dirtying config', async () => {
    const user = userEvent.setup();
    pickDirectoryMock.mockResolvedValue('/tmp/portable memory backups');
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          user_mode: 'expert',
        },
      },
    } as any);
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryData' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryData' });

    const vectorTitle = screen.getByText('settings.memory.vector.title');
    const dataManagement = screen.getByTestId('memory-data-management-section');
    const dangerZone = screen.getByTestId('memory-danger-zone');
    expect(vectorTitle.compareDocumentPosition(dataManagement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(dataManagement.compareDocumentPosition(dangerZone) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Immediate-action page: the draft save footer does not apply here.
    expect(screen.queryByText('settings.allChangesSaved')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.actions.save' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.backup.action',
    }));
    await user.click(screen.getByRole('button', {
      name: 'settings.memory.dataManagement.common.chooseDirectory',
    }));

    expect(screen.getByText('/tmp/portable memory backups')).toBeInTheDocument();
    expect(configApi.update).not.toHaveBeenCalled();
  });

  it('keeps memory data management visible in Quick mode', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        preferences: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.preferences),
          user_mode: 'quick',
        },
      },
    } as any);
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));

    expect(screen.getByRole('button', { name: 'settings.tabs.memoryGeneral' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.memoryData' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.memoryWorkbench' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryData' }));
    expect(await screen.findByTestId('memory-data-management-section')).toBeInTheDocument();
  });

  it('saves the workbench attention update cadence', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryWorkbench' }));

    const turnThresholdInput = await screen.findByLabelText(
      'settings.memory.fields.l0_attention_update_turn_threshold.label'
    );
    const idleSecondsInput = screen.getByLabelText(
      'settings.memory.fields.l0_attention_update_idle_seconds.label'
    );
    const maxDelayInput = screen.getByLabelText(
      'settings.memory.fields.l0_attention_update_max_delay_seconds.label'
    );

    expect(turnThresholdInput).toHaveValue(3);
    expect(idleSecondsInput).toHaveValue(30);
    expect(maxDelayInput).toHaveValue(90);

    fireEvent.change(turnThresholdInput, { target: { value: '5' } });
    fireEvent.change(idleSecondsInput, { target: { value: '45' } });
    fireEvent.change(maxDelayInput, { target: { value: '120' } });

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            l0: expect.objectContaining({
              attention_update_turn_threshold: 5,
              attention_update_idle_seconds: 45,
              attention_update_max_delay_seconds: 120,
            }),
          }),
        })
      )
    );
  });

  it('blocks saving when the workbench maximum delay is shorter than the idle wait', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryWorkbench' }));

    fireEvent.change(
      await screen.findByLabelText('settings.memory.fields.l0_attention_update_idle_seconds.label'),
      { target: { value: '120' } }
    );

    expect(screen.getByRole('alert')).toHaveTextContent(
      'settings.memory.validation.attentionUpdateMaxDelayTooShort'
    );
    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeDisabled();
    expect(configApi.update).not.toHaveBeenCalled();
  });

  it('saves layer-specific memory retention settings and keeps knowledge internals hidden', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    expect(screen.queryByLabelText('settings.memory.fields.db_path.label')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.actions.chooseDirectory' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('settings.memory.fields.retention_days.label')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.memory.fields.history_behavior.label' }));
    await user.click(screen.getByRole('button', { name: 'settings.memory.options.history_behavior.archive' }));

    expect(
      screen.queryByRole('switch', { name: 'settings.memory.fields.async_embeddings.label' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'settings.memory.fields.embedding_backend.label' })
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryEvents' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryEvents' });
    const l1RetentionInput = await screen.findByLabelText('settings.memory.fields.l1_retention_days.label');
    fireEvent.change(l1RetentionInput, { target: { value: '21' } });

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryKnowledge' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryKnowledge' });
    expect(
      screen.queryByLabelText('settings.memory.fields.l2_batch_flush_interval_seconds.label')
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memoryReflection' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryReflection' });
    const l3RetentionInput = await screen.findByLabelText('settings.memory.fields.l3_retention_days.label');
    fireEvent.change(l3RetentionInput, { target: { value: '240' } });

    await user.click(screen.getByRole('button', { name: 'settings.tabs.memorySkills' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memorySkills' });
    const l4RetentionInput = await screen.findByLabelText('settings.memory.fields.l4_inactive_skill_retention_days.label');
    fireEvent.change(l4RetentionInput, { target: { value: '45' } });
    const l4MinAttemptsInput = await screen.findByLabelText('settings.memory.fields.l4_inactive_skill_min_attempts.label');
    fireEvent.change(l4MinAttemptsInput, { target: { value: '9' } });

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            history_behavior: 'archive',
            l1: expect.objectContaining({
              retention_days: 21,
            }),
            l2: expect.objectContaining({
              batch_flush_interval_seconds: 60,
            }),
            l3: expect.objectContaining({
              retention_days: 240,
            }),
            l4: expect.objectContaining({
              inactive_skill_retention_days: 45,
              inactive_skill_min_attempts: 9,
            }),
          }),
        })
      )
    );
  });

  it('shows archive path only when historical memory is archived', async () => {
    const user = userEvent.setup();
    const defaultArchivePath = '~/.magi/data/memory/archive';
    pickDirectoryMock.mockResolvedValue('/tmp/magi-archive');
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    expect(screen.queryByLabelText('settings.memory.fields.archive_path.label')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.memory.fields.history_behavior.label' }));
    await user.click(screen.getByRole('button', { name: 'settings.memory.options.history_behavior.archive' }));

    const archivePathInput = await screen.findByLabelText('settings.memory.fields.archive_path.label');
    expect(archivePathInput).toHaveValue(defaultArchivePath);

    await user.click(screen.getByRole('button', { name: 'settings.actions.chooseDirectory' }));

    await waitFor(() => expect(pickDirectoryMock).toHaveBeenCalledWith(defaultArchivePath));
    expect(archivePathInput).toHaveValue('/tmp/magi-archive');

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            history_behavior: 'archive',
            archive_path: '/tmp/magi-archive',
          }),
        })
      )
    );
  });

  it('disables the cross-encoder toggle when no cross-encoder model is configured', async () => {
    const user = userEvent.setup();
    // Default config has managed_model_id: null → toggle must be disabled
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    const crossEncoderSwitch = screen.getByRole('switch', { name: 'settings.memory.fields.cross_encoder_enabled.label' });
    expect(crossEncoderSwitch).toBeDisabled();
    expect(screen.getByText('settings.memory.fields.cross_encoder_no_model_hint')).toBeInTheDocument();
  });

  it('enables the cross-encoder toggle when a cross-encoder model is configured', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        memory: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.memory),
          reranker: {
            ...structuredClone(DEFAULT_SYSTEM_CONFIG.memory.reranker),
            cross_encoder: {
              enabled: false,
              managed_model_id: 'bge-reranker-v2',
              variant: null,
            },
          },
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    const crossEncoderSwitch = screen.getByRole('switch', { name: 'settings.memory.fields.cross_encoder_enabled.label' });
    expect(crossEncoderSwitch).not.toBeDisabled();
    expect(screen.queryByText('settings.memory.fields.cross_encoder_no_model_hint')).not.toBeInTheDocument();

    await user.click(crossEncoderSwitch);

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            reranker: expect.objectContaining({
              cross_encoder: expect.objectContaining({
                enabled: true,
              }),
            }),
          }),
        })
      )
    );
  });

  it('does not render the reranker top_k field in the general memory section', async () => {
    const user = userEvent.setup();
    vi.mocked(configApi.get).mockResolvedValue({
      data: {
        ...structuredClone(DEFAULT_SYSTEM_CONFIG),
        memory: {
          ...structuredClone(DEFAULT_SYSTEM_CONFIG.memory),
          reranker: {
            ...structuredClone(DEFAULT_SYSTEM_CONFIG.memory.reranker),
            cross_encoder: {
              enabled: true,
              managed_model_id: 'bge-reranker-v2',
              variant: null,
            },
          },
        },
      },
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    expect(screen.queryByLabelText('settings.memory.fields.reranker_top_k.label')).not.toBeInTheDocument();
  });

  it('saves query expansion control from the general memory section', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    const maxExpansionsInput = await screen.findByLabelText('settings.memory.fields.query_expansion_max_expansions.label');
    fireEvent.change(maxExpansionsInput, { target: { value: '3' } });

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            query_expansion: expect.objectContaining({
              enabled: true,
              max_expansions: 3,
            }),
          }),
        })
      )
    );
  });

  it('saves graph spreading recall from the general memory section', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    const graphSpreadingSwitch = screen.getByRole('switch', { name: 'settings.memory.fields.graph_spreading_enabled.label' });
    expect(graphSpreadingSwitch).toHaveAttribute('data-state', 'checked');

    await user.click(graphSpreadingSwitch);
    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            graph_spreading: expect.objectContaining({
              enabled: false,
            }),
          }),
        })
      )
    );
  });

  it('hides query expansion count when query expansion is disabled', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryGeneral' });

    expect(screen.getByLabelText('settings.memory.fields.query_expansion_max_expansions.label')).toBeInTheDocument();

    await user.click(screen.getByRole('switch', { name: 'settings.memory.fields.query_expansion_enabled.label' }));

    expect(screen.queryByLabelText('settings.memory.fields.query_expansion_max_expansions.label')).not.toBeInTheDocument();
  });

  it('saves profile conflict confirmation reminders from knowledge memory settings', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memoryKnowledge' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryKnowledge' });

    await user.click(screen.getByRole('switch', { name: 'settings.memory.fields.shadow_conflict_notification_enabled.label' }));
    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            l2: expect.objectContaining({
              shadow_conflict_notification_enabled: false,
            }),
          }),
        })
      )
    );
  });

  it('saves portrait refresh delay from knowledge memory settings', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memory' }));
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.memoryKnowledge' }));
    await screen.findByRole('heading', { name: 'settings.tabs.memoryKnowledge' });

    const delayInput = await screen.findByLabelText(
      'settings.memory.fields.l2_portrait_projection_refresh_delay_seconds.label'
    );
    fireEvent.change(delayInput, { target: { value: '45' } });

    await user.click(screen.getByRole('button', { name: 'settings.actions.save' }));

    await waitFor(() =>
      expect(configApi.update).toHaveBeenCalledWith(
        expect.objectContaining({
          memory: expect.objectContaining({
            l2: expect.objectContaining({
              portrait_projection_refresh_delay_seconds: 45,
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

  it('saves source drafts to their connection independently of the global settings form', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));
    const photoPanel = await screen.findByTestId('timeline-source-detail-photo_library');
    fireEvent.change(within(photoPanel).getByLabelText('Sync Interval (minutes)'), { target: { value: '75' } });
    expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeDisabled();
    await user.click(within(photoPanel).getByRole('button', { name: 'plugins.connections.save' }));
    await waitFor(() => expect(pluginsApi.updateConnection).toHaveBeenCalledWith(
      'photo-library', 'photo-account', {
        expected_revision: 4,
        settings: { sensors: { photo_library: { sync_interval_minutes: 75 } } }, credentials: {},
      },
    ));
    expect(configApi.update).not.toHaveBeenCalled();
  });

  it('keeps drafts isolated between two accounts of the same package', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [
      { ...timelineSourceFixture, connection_id: 'personal', connection_display_name: 'Personal' },
      { ...timelineSourceFixture, connection_id: 'work', connection_display_name: 'Work' },
    ] } as any);
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));
    await user.click(await screen.findByRole('tab', { name: /Personal/ }));
    fireEvent.change(screen.getByLabelText('Sync Interval (minutes)'), { target: { value: '75' } });
    await user.click(screen.getByRole('tab', { name: /Work/ }));
    expect(screen.getByLabelText('Sync Interval (minutes)')).toHaveValue(60);
    fireEvent.change(screen.getByLabelText('Sync Interval (minutes)'), { target: { value: '90' } });
    await user.click(screen.getByRole('button', { name: 'plugins.connections.save' }));
    await waitFor(() => expect(pluginsApi.updateConnection).toHaveBeenCalledWith('photo-library', 'work', {
      expected_revision: 4, settings: { sensors: { photo_library: { sync_interval_minutes: 90 } } }, credentials: {},
    }));
    await user.click(screen.getByRole('tab', { name: /Personal/ }));
    expect(screen.getByLabelText('Sync Interval (minutes)')).toHaveValue(75);
    expect(pluginsApi.updateConnection).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeDisabled();
  });

  it('toggles one sensor flag while retaining sibling sources and connection enablement', async () => {
    const user = userEvent.setup();
    vi.mocked(pluginsApi.getConnection).mockResolvedValue({
      plugin_id: 'photo-library', connection_id: 'photo-account', display_name: 'Photos',
      enabled: true, revision: 8, credential_refs: {}, readiness: [],
      settings: { sensors: { photo_library: { enabled: true }, sibling: { enabled: true } } },
    });
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));
    await user.click(screen.getByRole('switch', { name: 'settings.timeline.fields.enabled' }));
    await waitFor(() => expect(pluginsApi.updateConnection).toHaveBeenCalledWith('photo-library', 'photo-account', {
      expected_revision: 8, credentials: {},
      settings: { sensors: { photo_library: { enabled: false }, sibling: { enabled: true } } },
    }));
  });

  it('requires account selection before exposing timeline controls and retains a failed draft', async () => {
    const user = userEvent.setup();
    const failure = vi.spyOn(toast, 'error').mockReturnValue('failure');
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [
      { ...timelineSourceFixture, connection_id: 'personal', connection_display_name: 'Personal' },
      { ...timelineSourceFixture, connection_id: 'work', connection_display_name: 'Work' },
    ] } as any);
    vi.mocked(pluginsApi.updateConnection).mockRejectedValueOnce(new Error('revision conflict'));
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));
    expect(screen.queryByRole('switch', { name: 'settings.timeline.fields.enabled' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Sync Interval (minutes)')).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /Work/ }));
    fireEvent.change(screen.getByLabelText('Sync Interval (minutes)'), { target: { value: '90' } });
    await user.click(screen.getByRole('button', { name: 'plugins.connections.save' }));
    await waitFor(() => expect(failure).toHaveBeenCalledWith('plugins.connections.saveFailed'));
    expect(screen.getByLabelText('Sync Interval (minutes)')).toHaveValue(90);
    expect(screen.getByRole('button', { name: 'plugins.connections.save' })).toBeEnabled();
    expect(pluginsApi.updateConnection).toHaveBeenCalledWith('photo-library', 'work', expect.any(Object));
  });

  it('does not discard an unsaved source field when toggling its sensor flag', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));
    fireEvent.change(screen.getByLabelText('Sync Interval (minutes)'), { target: { value: '90' } });
    await user.click(screen.getByRole('switch', { name: 'settings.timeline.fields.enabled' }));
    await waitFor(() => expect(pluginsApi.updateConnection).toHaveBeenCalledWith('photo-library', 'photo-account', {
      expected_revision: 4, credentials: {}, settings: { sensors: { photo_library: { enabled: false } } },
    }));
    expect(screen.getByLabelText('Sync Interval (minutes)')).toHaveValue(90);
    expect(screen.getByRole('button', { name: 'plugins.connections.save' })).toBeEnabled();
  });

  it('does not write a source draft after switching accounts during its revision lookup', async () => {
    const user = userEvent.setup();
    let resolveRead!: (value: Awaited<ReturnType<typeof pluginsApi.getConnection>>) => void;
    vi.mocked(pluginsApi.getConnection).mockReturnValueOnce(new Promise((resolve) => { resolveRead = resolve; }));
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [
      { ...timelineSourceFixture, connection_id: 'personal', connection_display_name: 'Personal' },
      { ...timelineSourceFixture, connection_id: 'work', connection_display_name: 'Work' },
    ] } as any);
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));
    await user.click(screen.getByRole('tab', { name: /Personal/ }));
    fireEvent.change(screen.getByLabelText('Sync Interval (minutes)'), { target: { value: '75' } });
    await user.click(screen.getByRole('button', { name: 'plugins.connections.save' }));
    await user.click(screen.getByRole('tab', { name: /Work/ }));
    resolveRead({ plugin_id: 'photo-library', connection_id: 'personal', revision: 4, settings: {} } as never);
    await waitFor(() => expect(screen.getByLabelText('Sync Interval (minutes)')).toHaveValue(60));
    expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
    await user.click(screen.getByRole('tab', { name: /Personal/ }));
    expect(screen.getByLabelText('Sync Interval (minutes)')).toHaveValue(75);
  });

  it('queues a historical backfill from timeline source settings', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          enabled: true,
          activation_required: false,
          current_settings: {
            ...chromeTimelineSourceFixture.current_settings,
            'sensors.chrome_history.enabled': true,
            'sensors.chrome_history.initial_sync_configured': true,
          },
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    await user.click(within(chromePanel).getByRole('button', { name: '补旧数据' }));
    await user.click(await screen.findByRole('button', { name: '开始补回' }));

    await waitFor(() =>
      expect(sensorsApi.requestSync).toHaveBeenCalledWith('chrome_history', 'chrome-account', {
        mode: 'backfill',
        backfillScope: 'last_30_days',
      })
    );
  });

  it('shows durable retry progress without treating it as a terminal source error', async () => {
    const user = userEvent.setup();
    const nextAttemptAt = 1_773_228_600;
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          enabled: true,
          status: 'retrying',
          last_error: 'temporary source failure',
          sync_activity: {
            job_id: 'retry-job-1',
            mode: 'latest',
            status: 'retrying',
            attempt_count: 2,
            next_attempt_at: nextAttemptAt,
            error: 'temporary source failure',
          },
          current_settings: {
            ...chromeTimelineSourceFixture.current_settings,
            'sensors.chrome_history.enabled': true,
            'sensors.chrome_history.initial_sync_configured': true,
          },
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    const expectedRetryTime = new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(nextAttemptAt * 1000));

    expect(within(chromePanel).getAllByText('等待重试（已尝试 2 次）')).not.toHaveLength(0);
    expect(within(chromePanel).getAllByText(expectedRetryTime)).not.toHaveLength(0);
    expect(
      within(chromePanel).getByRole('button', { name: 'settings.timeline.actions.syncNow' })
    ).toBeDisabled();
    expect(within(chromePanel).getByRole('button', { name: '补旧数据' })).toBeDisabled();
    expect(within(chromePanel).queryByText('temporary source failure')).not.toBeInTheDocument();
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

  it('shows a marketplace entry point when no timeline sources are registered', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [] } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    const emptyState = await screen.findByTestId('settings-empty-state-timeline-sources');

    expect(within(emptyState).getByText('settings.timeline.workspace.emptyTitle')).toBeInTheDocument();
    expect(within(emptyState).getByText('settings.timeline.workspace.emptyDescription')).toBeInTheDocument();

    await user.click(within(emptyState).getByRole('button', { name: 'settings.timeline.workspace.emptyAction' }));

    expect(await screen.findByRole('heading', { name: 'settings.tabs.pluginsMarketplace' })).toBeInTheDocument();
  });

  it('shows a matching marketplace entry point when no channel plugins are installed', async () => {
    const user = userEvent.setup();

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.channels' }));
    const emptyState = await screen.findByTestId('settings-empty-state-channels');

    expect(within(emptyState).getByText('settings.channelsConfig.emptyTitle')).toBeInTheDocument();
    expect(within(emptyState).getByText('settings.channelsConfig.emptyDescription')).toBeInTheDocument();

    await user.click(within(emptyState).getByRole('button', { name: 'settings.channelsConfig.emptyAction' }));

    expect(await screen.findByRole('heading', { name: 'settings.tabs.pluginsMarketplace' })).toBeInTheDocument();
  });

  it('groups multiple source entries under one capability workspace', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...timelineSourceFixture,
          source_name: 'photo_library_apple_photos',
          contribution_id: 'timeline.photo_library.apple_photos',
          display_name: 'Apple Photos',
          display_name_translated: 'Apple Photos',
          description: 'Read the macOS Photos library directly.',
          description_translated: '直接读取 macOS 照片图库。',
          capability_id: 'photo_library',
          capability_display_name: 'Photo Library',
          capability_display_name_translated: '照片库',
          capability_description: 'Manage photo sources.',
          capability_description_translated: '统一管理照片进入时间线的方式。',
          entry_id: 'apple_photos',
          entry_display_name: 'Apple Photos',
          entry_display_name_translated: 'Apple Photos',
          enabled: true,
          supports_pull_sync: true,
          last_error: '需要照片权限',
          fields: [
            {
              ...timelineSourceFixture.fields[0],
              key: 'sensors.photo_library_apple_photos.enabled',
              label_translated: '启用',
            },
          ],
          current_settings: {
            'sensors.photo_library_apple_photos.enabled': true,
          },
        },
        {
          ...timelineSourceFixture,
          source_name: 'photo_library_directory',
          contribution_id: 'timeline.photo_library.directory',
          display_name: 'Local Photos',
          display_name_translated: '本地照片',
          description: 'Scan local photo folders.',
          description_translated: '扫描你选择的本地照片文件夹。',
          capability_id: 'photo_library',
          capability_display_name: 'Photo Library',
          capability_display_name_translated: '照片库',
          capability_description: 'Manage photo sources.',
          capability_description_translated: '统一管理照片进入时间线的方式。',
          entry_id: 'directory',
          entry_display_name: 'Local Photos',
          entry_display_name_translated: '本地照片',
          enabled: true,
          supports_pull_sync: true,
          fields: [
            {
              ...timelineSourceFixture.fields[0],
              key: 'sensors.photo_library_directory.enabled',
              label_translated: '启用',
            },
          ],
          current_settings: {
            'sensors.photo_library_directory.enabled': true,
          },
        },
        {
          ...chromeTimelineSourceFixture,
          capability_id: 'browser_history',
          capability_display_name: 'Browser History',
          capability_display_name_translated: '浏览器历史',
          capability_description: 'Manage browser history sources.',
          capability_description_translated: '统一管理浏览器历史进入时间线的方式。',
          entry_id: 'chrome',
          entry_display_name: 'Chrome',
          entry_display_name_translated: 'Chrome',
          enabled: true,
        },
        {
          ...chromeTimelineSourceFixture,
          source_name: 'safari_history',
          plugin_id: 'safari-history',
          contribution_id: 'timeline.safari_history',
          display_name: 'Safari History',
          display_name_translated: 'Safari',
          description: 'Local Safari browsing history ingested into the user timeline.',
          capability_id: 'browser_history',
          capability_display_name: 'Browser History',
          capability_display_name_translated: '浏览器历史',
          capability_description: 'Manage browser history sources.',
          capability_description_translated: '统一管理浏览器历史进入时间线的方式。',
          entry_id: 'safari',
          entry_display_name: 'Safari',
          entry_display_name_translated: 'Safari',
          enabled: true,
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await screen.findByTestId('timeline-overview');

    expect(await screen.findByTestId('timeline-nav-source-photo_library')).toHaveTextContent('照片库');
    expect(await screen.findByTestId('timeline-nav-source-browser_history')).toHaveTextContent('浏览器历史');
    expect(screen.queryByTestId('timeline-nav-source-photo_library_apple_photos')).not.toBeInTheDocument();
    expect(screen.queryByTestId('timeline-nav-source-chrome_history')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('timeline-nav-source-photo_library'));
    const photoWorkspace = await screen.findByTestId('timeline-capability-detail-photo_library');
    expect(within(photoWorkspace).getByTestId('timeline-entry-selector-photo_library')).toBeInTheDocument();
    expect(within(photoWorkspace).getByTestId('timeline-entry-option-photo_library_apple_photos')).toHaveTextContent('Apple Photos');
    expect(within(photoWorkspace).getByTestId('timeline-entry-option-photo_library_directory')).toHaveTextContent('本地照片');
    expect(within(photoWorkspace).getByTestId('timeline-entry-detail-photo_library_apple_photos')).toBeInTheDocument();

    await user.click(screen.getByTestId('timeline-nav-source-browser_history'));
    const browserWorkspace = await screen.findByTestId('timeline-capability-detail-browser_history');
    expect(within(browserWorkspace).getByTestId('timeline-entry-selector-browser_history')).toBeInTheDocument();
    expect(within(browserWorkspace).getByTestId('timeline-entry-selector-scroll-browser_history')).toHaveClass(
      'overflow-x-auto'
    );
    expect(within(browserWorkspace).getByTestId('timeline-entry-selector-scroll-browser_history')).toHaveClass(
      'flex'
    );
    expect(within(browserWorkspace).getByTestId('timeline-entry-option-chrome_history')).toHaveTextContent('Chrome');
    expect(within(browserWorkspace).getByTestId('timeline-entry-option-safari_history')).toHaveTextContent('Safari');
    await user.click(within(browserWorkspace).getByTestId('timeline-entry-option-safari_history'));
    expect(within(browserWorkspace).getByTestId('timeline-entry-detail-safari_history')).toBeInTheDocument();
  });

  it('shows addable marketplace entries when a capability has only one installed source', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          capability_id: 'browser_history',
          capability_display_name: 'Browser History',
          capability_display_name_translated: '浏览器历史',
          capability_description: 'Manage browser history sources.',
          capability_description_translated: '统一管理浏览器历史入口。',
          entry_id: 'chrome',
          entry_display_name: 'Chrome',
          entry_display_name_translated: 'Chrome',
          enabled: true,
        },
      ],
    } as any);
    vi.mocked(pluginsApi.getRegistry).mockResolvedValue({
      registry_version: '4',
      install_fingerprint: 'fingerprint-1',
      plugins: [
        browserRegistryEntry('chrome-history', 'Chrome History', 'Chrome', 10, true),
        browserRegistryEntry('safari-history', 'Safari History', 'Safari', 20, false),
        browserRegistryEntry('firefox-history', 'Firefox History', 'Firefox', 30, false),
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-browser_history'));
    const browserWorkspace = await screen.findByTestId('timeline-capability-detail-browser_history');

    expect(within(browserWorkspace).getByTestId('timeline-entry-selector-browser_history')).toBeInTheDocument();
    expect(within(browserWorkspace).getByTestId('timeline-entry-option-chrome_history')).toHaveTextContent('Chrome');
    expect(within(browserWorkspace).getByTestId('timeline-available-entry-selector-browser_history')).toBeInTheDocument();
    expect(within(browserWorkspace).getByText('settings.timeline.workspace.availableEntriesTitle')).toBeInTheDocument();
    expect(within(browserWorkspace).getByTestId('timeline-marketplace-entry-safari-history')).toHaveTextContent('Safari');
    expect(within(browserWorkspace).getByTestId('timeline-marketplace-entry-firefox-history')).toHaveTextContent('Firefox');
    expect(within(browserWorkspace).queryByTestId('timeline-marketplace-entry-chrome-history')).not.toBeInTheDocument();

    await user.click(
      within(
        browserWorkspace,
      ).getByTestId('timeline-marketplace-entry-safari-history').querySelector('button')!,
    );
    expect(await screen.findByText('plugins.trust.nativeAccess')).toBeInTheDocument();
    await user.click(
      await screen.findByRole('button', {
        name: 'settings.marketplace.consent.confirm.install',
      }),
    );

    await waitFor(() => {
      expect(pluginsApi.installFromRegistryWithProgress).toHaveBeenCalledWith(
        'safari-history',
        'fingerprint-1',
        expect.any(Function),
      );
    });
  });

  it('shows the installed entry option even for single-entry sensor details', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...timelineSourceFixture,
          source_name: 'git_activity',
          plugin_id: 'git-activity',
          contribution_id: 'timeline.git_activity',
          display_name: 'Git Activity',
          display_name_translated: 'Git 活动',
          description: 'Git repository activity ingestion for the timeline.',
          description_translated: 'Git 仓库活动接入时间线。',
          current_settings: {
            'sensors.git_activity.enabled': false,
            'sensors.git_activity.sync_interval_minutes': 30,
          },
          enabled: false,
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-git_activity'));

    const panel = await screen.findByTestId('timeline-capability-detail-git_activity');
    expect(within(panel).getAllByRole('heading', { name: 'Git 活动' })).toHaveLength(1);
    expect(within(panel).getByTestId('timeline-entry-selector-git_activity')).toBeInTheDocument();
    expect(within(panel).getByTestId('timeline-entry-option-git_activity')).toHaveTextContent('Git 活动');
    expect(within(panel).getByTestId('timeline-source-header-actions')).toBeInTheDocument();
  });

  it('renders photo-library source tabs and scopes fields to the selected source', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...timelineSourceFixture,
          enabled: false,
          supports_pull_sync: true,
          display_name_translated: '照片库',
          description_translated: '读取 Apple Photos 或本地照片目录，提取拍摄时间、地点和设备信息并接入时间线',
          current_settings: {
            'sensors.photo_library.enabled': false,
            'sensors.photo_library.source_mode': 'apple_photos',
            'sensors.photo_library.photos_library_path': '~/Pictures/Photos Library.photoslibrary',
            'sensors.photo_library.source_paths': [],
            'sensors.photo_library.sync_mode': 'manual',
            'sensors.photo_library.max_items_per_sync': 200,
          },
          fields: [
            {
              key: 'sensors.photo_library.enabled',
              type: 'switch',
              label: 'Enable',
              label_translated: '启用',
              description: 'Whether photo library sync is active.',
              default: false,
              required: false,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 10,
            },
            {
              key: 'sensors.photo_library.source_mode',
              type: 'select',
              label: 'Source',
              label_translated: '来源',
              description: 'Choose a source.',
              default: 'directory',
              required: false,
              options: [
                { label: 'Photo directories', label_translated: '本地照片', value: 'directory' },
                { label: 'Apple Photos', label_translated: 'Apple Photos', value: 'apple_photos' },
              ],
              section: 'general',
              surface: 'timeline',
              order: 12,
            },
            {
              key: 'sensors.photo_library.photos_library_path',
              type: 'path',
              label: 'Apple Photos Library',
              label_translated: 'Apple Photos 照片库',
              description: 'Path to the .photoslibrary package.',
              default: '~/Pictures/Photos Library.photoslibrary',
              required: true,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 14,
              depends_on_key: 'sensors.photo_library.source_mode',
              depends_on_values: ['apple_photos'],
            },
            {
              key: 'sensors.photo_library.source_paths',
              type: 'path',
              label: 'Photo Directories',
              label_translated: '本地照片目录',
              description: 'Local directories containing photos.',
              default: [],
              required: true,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 15,
              depends_on_key: 'sensors.photo_library.source_mode',
              depends_on_values: ['directory'],
            },
            {
              key: 'sensors.photo_library.max_items_per_sync',
              type: 'number',
              label: 'Max Items Per Sync',
              label_translated: '单次最大数量',
              description: 'Maximum number of photos to process per sync run.',
              default: 200,
              required: false,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 40,
            },
          ],
          settings_layout: {
            kind: 'tabs',
            controller_key: 'sensors.photo_library.source_mode',
            tabs: [
              {
                tab_id: 'directory',
                value: 'directory',
                label: 'Photo folders',
                label_translated: '本地照片',
                description: 'Scan exported photo folders.',
                description_translated: '扫描你选择的本地照片文件夹。',
                available: true,
              },
              {
                tab_id: 'apple_photos',
                value: 'apple_photos',
                label: 'Apple Photos',
                label_translated: 'Apple Photos',
                description: 'Read the macOS Photos library.',
                description_translated: '直接读取 macOS 照片图库。',
                available: true,
                platforms: ['darwin'],
              },
            ],
          },
        },
      ],
    } as any);
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));

    const photoPanel = await screen.findByTestId('timeline-source-detail-photo_library');
    expect(within(photoPanel).getByRole('tab', { name: '本地照片' })).toBeInTheDocument();
    expect(within(photoPanel).getByRole('tab', { name: 'Apple Photos' })).toHaveAttribute('aria-selected', 'true');
    expect(within(photoPanel).queryByText('来源')).not.toBeInTheDocument();
    expect(within(photoPanel).getByText('Apple Photos 照片库')).toBeInTheDocument();
    expect(within(photoPanel).queryByText('本地照片目录')).not.toBeInTheDocument();
    expect(within(photoPanel).queryByText('拉取同步：可用')).not.toBeInTheDocument();

    await user.click(within(photoPanel).getByRole('tab', { name: '本地照片' }));

    expect(within(photoPanel).getByText('本地照片目录')).toBeInTheDocument();
    expect(within(photoPanel).queryByText('Apple Photos 照片库')).not.toBeInTheDocument();

    await user.click(within(photoPanel).getByRole('button', { name: 'plugins.connections.save' }));

    await waitFor(() =>
      expect(pluginsApi.updateConnection).toHaveBeenCalledWith(
        'photo-library', 'photo-account',
        expect.objectContaining({ expected_revision: 4, settings: { sensors: { photo_library: { source_mode: 'directory' } } } })
      )
    );
  });

  it('shows platform unavailable reason for unavailable photo-library source tabs', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...timelineSourceFixture,
          display_name_translated: '照片库',
          current_settings: {
            'sensors.photo_library.enabled': false,
            'sensors.photo_library.source_mode': 'apple_photos',
            'sensors.photo_library.photos_library_path': '~/Pictures/Photos Library.photoslibrary',
            'sensors.photo_library.source_paths': [],
          },
          fields: [
            {
              key: 'sensors.photo_library.enabled',
              type: 'switch',
              label: 'Enable',
              label_translated: '启用',
              description: 'Whether photo library sync is active.',
              default: false,
              required: false,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 10,
            },
            {
              key: 'sensors.photo_library.source_mode',
              type: 'select',
              label: 'Source',
              label_translated: '来源',
              description: 'Choose a source.',
              default: 'directory',
              required: false,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 12,
            },
            {
              key: 'sensors.photo_library.photos_library_path',
              type: 'path',
              label: 'Apple Photos Library',
              label_translated: 'Apple Photos 照片库',
              description: 'Path to the .photoslibrary package.',
              default: '~/Pictures/Photos Library.photoslibrary',
              required: true,
              options: [],
              section: 'general',
              surface: 'timeline',
              order: 14,
              depends_on_key: 'sensors.photo_library.source_mode',
              depends_on_values: ['apple_photos'],
            },
          ],
          settings_ui_blocks: [
            {
              block_id: 'apple_photos_permissions',
              type: 'resource_picker',
              title: 'Apple Photos Access',
              title_translated: 'Apple Photos 访问权限',
              description: 'Apple Photos mode needs permissions.',
              description_translated: 'Apple Photos 模式需要权限。',
              resource_name: 'apple_photos_permissions',
              value_key: '_readonly',
              presentation: 'permission_status',
              depends_on_key: 'sensors.photo_library.source_mode',
              depends_on_values: ['apple_photos'],
            },
          ],
          settings_layout: {
            kind: 'tabs',
            controller_key: 'sensors.photo_library.source_mode',
            tabs: [
              {
                tab_id: 'directory',
                value: 'directory',
                label: 'Photo folders',
                label_translated: '本地照片',
                available: true,
              },
              {
                tab_id: 'apple_photos',
                value: 'apple_photos',
                label: 'Apple Photos',
                label_translated: 'Apple Photos',
                available: false,
                unavailable_reason: 'Apple Photos is only available on macOS.',
                unavailable_reason_translated: 'Apple Photos 仅在 macOS 上可用。',
                platforms: ['darwin'],
              },
            ],
          },
        },
      ],
    } as any);
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-photo_library'));

    const photoPanel = await screen.findByTestId('timeline-source-detail-photo_library');
    expect(within(photoPanel).getByRole('tab', { name: 'Apple Photos' })).toHaveAttribute('aria-disabled', 'true');
    expect(within(photoPanel).getByText('Apple Photos 仅在 macOS 上可用。')).toBeInTheDocument();
    expect(within(photoPanel).queryByText('Apple Photos 访问权限')).not.toBeInTheDocument();
    expect(within(photoPanel).queryByText('Apple Photos 照片库')).not.toBeInTheDocument();
  });

  it('renders settings actions declared by timeline source plugins', async () => {
    const user = userEvent.setup();
    vi.mocked(pluginsApi.startSettingsAction).mockResolvedValueOnce({
      plugin_id: 'github-activity',
      action_id: 'connect_github',
      session_id: 'session-1',
      connection_id: 'github-account',
      status: 'pending',
      message: 'Open GitHub and enter ABCD-EFGH.',
      data: {
        open_url: 'https://github.com/login/device',
        verification_uri: 'https://github.com/login/device',
        user_code: 'ABCD-EFGH',
      },
      settings_updates: {},
    } as any);
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          connection_id: 'github-account',
          source_name: 'github_activity',
          plugin_id: 'github-activity',
          contribution_id: 'timeline.github_activity',
          display_name: 'GitHub Activity',
          description: 'Local GitHub repository activity.',
          current_settings: {
            'sensors.github_activity.enabled': false,
            'sensors.github_activity.repositories': ['acme/app'],
          },
          fields: [
            {
              key: 'sensors.github_activity.repositories',
              type: 'tags',
              label: 'Repositories',
              description: 'Repositories to sync.',
              default: [],
              required: false,
              options: [],
              section: 'connection',
              surface: 'timeline',
              order: 10,
            },
          ],
          settings_actions: [
            {
              action_id: 'connect_github',
              label: 'Connect GitHub',
              description: 'Authorize GitHub locally.',
              button_label: 'Connect GitHub',
              presentation: 'inline',
              surface: 'timeline',
              contribution_id: 'timeline.github_activity',
              contribution_type: 'sensor',
              order: 0,
              destructive: false,
              requires_enabled: false,
              poll_interval_ms: 5000,
              timeout_ms: 900000,
              persist_settings_on_success: true,
            },
          ],
        },
      ],
    } as any);
    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-github_activity'));

    const panel = await screen.findByTestId('timeline-source-detail-github_activity');
    await user.click(within(panel).getByRole('button', { name: 'Connect GitHub' }));

    expect(pluginsApi.startSettingsAction).toHaveBeenCalledWith(
      'github-account',
      'connect_github',
      expect.objectContaining({
        'sensors.github_activity.repositories': ['acme/app'],
      })
    );
    await waitFor(() => {
      expect(openExternalUrlMock).toHaveBeenCalledWith('https://github.com/login/device');
    });
  });

  it('keeps timeline nav items alphabetized after overview', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
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

  it('persists activation directly to the selected connection', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));
    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    await user.click(within(chromePanel).getByRole('switch', { name: 'settings.timeline.fields.enabled' }));
    expect(await screen.findByText('Enable Chrome History')).toBeInTheDocument();
    expect(pluginsApi.updateConnection).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Enable source' }));
    await waitFor(() => expect(pluginsApi.updateConnection).toHaveBeenCalledWith(
      'chrome-history', 'chrome-account', expect.objectContaining({
        expected_revision: 4,
        settings: { sensors: { chrome_history: expect.objectContaining({ enabled: true, initial_sync_configured: true }) } },
      }),
    ));
    expect(screen.getByRole('button', { name: 'settings.actions.save' })).toBeDisabled();
  });

  it('keeps an unconfigured source non-operational even if enabled was set directly', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          enabled: true,
          activation_required: true,
          current_settings: {
            ...chromeTimelineSourceFixture.current_settings,
            'sensors.chrome_history.enabled': true,
            'sensors.chrome_history.initial_sync_configured': false,
          },
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-chrome_history'));

    const chromePanel = await screen.findByTestId('timeline-source-detail-chrome_history');
    const enabledSwitch = within(chromePanel).getByRole('switch', {
      name: 'settings.timeline.fields.enabled',
    });
    expect(enabledSwitch).not.toBeChecked();
    expect(
      within(chromePanel).queryByRole('button', { name: 'settings.timeline.actions.syncNow' })
    ).not.toBeInTheDocument();

    await user.click(enabledSwitch);

    expect(await screen.findByText('Enable Chrome History')).toBeInTheDocument();
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
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...chromeTimelineSourceFixture,
          // Backend now serves pre-translated values via API; the host i18n
          // table no longer carries per-plugin entries (Phase 4).
          description_translated: '本地 Google Chrome 浏览器历史接入时间线',
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
              label_translated: '配置档案',
              description: 'Chrome profile directory to read, such as Default or Profile 1.',
              description_translated: '要读取的 Chrome 配置目录，例如 Default 或 Profile 1。',
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
              label_translated: '同步方式',
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
              label_translated: '定时间隔',
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
    expect(within(chromePanel).getAllByText('Chrome 历史').length).toBeGreaterThan(0);
    expect(within(chromePanel).getByText('配置档案')).toBeInTheDocument();
    expect(within(chromePanel).getByText('同步方式')).toBeInTheDocument();
    expect(within(chromePanel).queryByText('Chrome Data Path')).not.toBeInTheDocument();
    expect(within(chromePanel).queryByText('Edge Whitelist')).not.toBeInTheDocument();
    // ``定时间隔`` is the label for ``sync_interval_minutes`` which is hidden when
    // ``sync_mode=manual`` via depends_on_values.
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

  it('shows a flush-state action for app usage and queues it locally', async () => {
    const user = userEvent.setup();
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: [
        {
          ...timelineSourceFixture,
          source_name: 'screen_time',
          plugin_id: 'screen-time',
          contribution_id: 'timeline.screen_time',
          display_name: 'App Usage',
          description: 'Event-driven frontmost app usage aggregated into hourly summaries.',
          supports_pull_sync: true,
          supports_state_flush: true,
          fields: [
            {
              ...timelineSourceFixture.fields[0],
              key: 'sensors.screen_time.enabled',
            },
          ],
          current_settings: {
            'sensors.screen_time.enabled': true,
          },
        },
      ],
    } as any);

    render(<SettingsPage />);

    await user.click(await screen.findByRole('button', { name: 'settings.tabs.timeline' }));
    await user.click(await screen.findByTestId('timeline-nav-source-screen_time'));

    const panel = await screen.findByTestId('timeline-source-detail-screen_time');
    await user.click(within(panel).getByRole('button', { name: 'settings.timeline.actions.flushStateNow' }));

    await waitFor(() => expect(sensorsApi.requestStateFlush).toHaveBeenCalledWith('screen_time', 'photo-account'));
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

  it('shows grouped tools navigation with dedicated sub-sections', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const toolsGroupButton = await screen.findByRole('button', { name: 'settings.tabs.tools' });

    expect(toolsGroupButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'settings.tabs.toolsBuiltin' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.toolsPlugins' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'settings.tabs.toolsSkills' })).not.toBeInTheDocument();

    await user.click(toolsGroupButton);

    expect(toolsGroupButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'settings.tabs.toolsBuiltin' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.toolsPlugins' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'settings.tabs.toolsSkills' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'settings.tabs.toolsBuiltin' })).toBeInTheDocument();
    expect(screen.getByText('tools-config')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.toolsPlugins' }));

    expect(screen.getByRole('heading', { name: 'settings.tabs.toolsPlugins' })).toBeInTheDocument();
    expect(screen.getByText('tools-config')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.tabs.toolsSkills' }));

    expect(screen.getByRole('heading', { name: 'settings.tabs.toolsSkills' })).toBeInTheDocument();
    expect(await screen.findByText('browser')).toBeInTheDocument();
  });

  it('filters tools by whether they expose configurable fields', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    const toolsGroupButton = await screen.findByRole('button', { name: 'settings.tabs.tools' });
    await user.click(toolsGroupButton);

    expect(screen.getByText('Weather')).toBeInTheDocument();
    expect(screen.getByText('Web Search')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.toolsFilter.withConfig' }));

    expect(screen.getByText('Weather')).toBeInTheDocument();
    expect(screen.queryByText('Web Search')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.toolsFilter.withoutConfig' }));

    expect(screen.queryByText('Weather')).not.toBeInTheDocument();
    expect(screen.getByText('Web Search')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'settings.toolsFilter.all' }));

    expect(screen.getByText('Weather')).toBeInTheDocument();
    expect(screen.getByText('Web Search')).toBeInTheDocument();
  });

});
