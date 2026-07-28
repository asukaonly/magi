import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { toast } from 'sonner';

import { memoryApi } from '@/api/modules/memory';
import { pluginsApi } from '@/api/modules/plugins';
import { sensorsApi } from '@/api/modules/sensors';
import { MemorySourceDetailPage, MemorySourcesPage } from '@/pages/memory-pages';
import { useChatShellStore } from '@/stores';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

const { mockUseInstallableSensors } = vi.hoisted(() => ({
  mockUseInstallableSensors: vi.fn(),
}));

vi.mock('@/hooks/useInstallableSensors', () => ({
  useInstallableSensors: () => mockUseInstallableSensors(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const translations: Record<string, string> = {
        'memory.sourcesPage.title': '来源',
        'memory.sourcesPage.subtitle': '看看 Magi 今天从哪里形成记忆',
        'memory.sourcesPage.sections.pulse': '今日脉搏',
        'memory.sourcesPage.sections.ledger': '已连接来源',
        'memory.sourcesPage.empty.title': '连接第一个来源',
        'memory.sourcesPage.empty.body': '把日历、浏览、照片或终端活动接入 Magi，记忆会从这些真实经历中逐渐形成。',
        'memory.sourcesPage.empty.privacy': '来源数据只保存在本机。',
        'timeline.emptyState.sourcePageHeading': '可以从这些来源开始',
        'timeline.emptyState.connect': '启用',
        'timeline.emptyState.installAndConnect': '安装并启用',
        'timeline.emptyState.browseSources': '浏览全部来源',
        'memory.sourcesPage.columns.source': '来源',
        'memory.sourcesPage.columns.status': '状态',
        'memory.sourcesPage.columns.lastSync': '最近同步',
        'memory.sourcesPage.columns.today': '今日事件',
        'memory.sourcesPage.columns.stored': '已入库',
        'memory.sourcesPage.columns.action': '操作',
        'memory.sourcesPage.actions.view': '查看',
        'memory.sourcesPage.actions.sync': '同步一次',
        'memory.sourcesPage.actions.backfill': '补旧数据',
        'memory.sourcesPage.actions.settings': '打开设置',
        'memory.sourcesPage.actions.pause': '暂停',
        'memory.sourcesPage.actions.resume': '恢复',
        'memory.sourcesPage.actions.more': '更多操作',
        'memory.sourcesPage.actions.add': '添加来源',
        'memory.sourcesPage.pulseEmpty': '今天还没有来源活动；有新内容进入记忆后会显示在这里。',
        'memory.sourcesPage.feedback.backfillQueued': '{{source}} 已开始在后台补旧数据',
        'memory.sourcesPage.feedback.backfillCompleted': '{{source}} 补数据已完成',
        'memory.sourcesPage.feedback.backfillFailed': '{{source}} 补数据失败：{{message}}',
        'memory.sourcesPage.backfillStatus.queued': '等待补数据',
        'memory.sourcesPage.backfillStatus.running': '补数据中',
        'memory.sourcesPage.backfillStatus.retrying': '补数据重试中（已尝试 {{count}} 次）',
        'memory.sourcesPage.detail.backfillRange': '补数据范围：{{range}}',
        'sourceBackfill.title': '补回历史',
        'sourceBackfill.description': '选择 {{source}} 要补回的范围。',
        'sourceBackfill.rangeLabel': '时间范围',
        'sourceBackfill.ranges.last7Days': '近 7 天',
        'sourceBackfill.ranges.last30Days': '近 30 天',
        'sourceBackfill.ranges.full': '全部历史',
        'sourceBackfill.ranges.custom': '自定义',
        'sourceBackfill.custom.start': '开始日期',
        'sourceBackfill.custom.end': '结束日期',
        'sourceBackfill.custom.errorRequired': '请选择开始和结束日期',
        'sourceBackfill.custom.errorOrder': '结束日期不能早于开始日期',
        'sourceBackfill.idempotencyNote': '重复记录会自动跳过。',
        'sourceBackfill.cancel': '取消',
        'sourceBackfill.submit': '开始补回',
        'memory.sourcesPage.syncModes.interval': '定时同步',
        'memory.sourcesPage.syncModes.manual': '手动同步',
        'memory.sourcesPage.detail.recentTitle': '最近进入记忆的内容',
        'memory.sourcesPage.detail.recentCountDetailed': '已显示 {{shown}} / 共 {{total}} 条',
        'memory.sourcesPage.detail.searchPlaceholder': '搜索内容',
        'memory.sourcesPage.detail.searchAction': '搜索',
        'memory.sourcesPage.detail.loadMore': '加载更多',
        'memory.sourcesPage.detail.loadingMore': '正在加载',
        'memory.sourcesPage.detail.timeRange.all': '全部',
        'memory.sourcesPage.detail.timeRange.today': '今天',
        'memory.sourcesPage.detail.timeRange.last7Days': '近 7 天',
        'memory.sourcesPage.detail.timeRange.last30Days': '近 30 天',
        'memory.sourcesPage.detail.timeRange.custom': '自定义',
        'memory.sourcesPage.detail.customStart': '开始日期',
        'memory.sourcesPage.detail.customEnd': '结束日期',
        'memory.sourcesPage.detail.applyCustomRange': '应用',
        'memory.sourcesPage.detail.visitCount': '访问 {{count}} 次',
        'memory.sourcesPage.localOnly': '数据只保存在本机',
        'memory.sourcesPage.pulseStats.today': '今日事件',
        'memory.sourcesPage.pulseStats.backlog': '待处理',
        'memory.sourcesPage.pulseStats.errors': '异常',
        'memory.overview.sourceStatus.ready': '正常',
        'memory.overview.sourceStatus.stale': '延迟',
        'memory.overview.sourceStatus.setup_required': '待配置',
        'memory.sources.chrome_history': 'Chrome 历史',
        'memory.sources.claude_code_agent_history': 'Claude Code',
        'memory.sources.netease_music': '网易云音乐',
      };
      let result = translations[key] ?? options?.defaultValue ?? key;
      if (options) {
        for (const [name, value] of Object.entries(options)) {
          result = result.replace(`{{${name}}}`, String(value));
        }
      }
      return result;
    },
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/api/modules/memory', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/memory')>('@/api/modules/memory');
  return {
    ...actual,
    memoryApi: {
      ...actual.memoryApi,
      getDashboard: vi.fn(),
      getL1Events: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/sensors', () => ({
  sensorsApi: {
    getStatus: vi.fn(),
    getTodaySummary: vi.fn(),
    requestSync: vi.fn(),
  },
}));

vi.mock('@/api/modules/plugins', () => ({
  pluginsApi: {
    updateSettings: vi.fn(),
  },
}));

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const dashboardPayload = {
  statistics: {
    l0: { active_sessions: 0, total_attention_items: 0 },
    l1: { event_count: 288 },
    l2: { relation_count: 0, assertion_count: 0 },
    l3: { summary_count: 0 },
    l4: { skill_count: 0, open_circuit_breakers: 0 },
  },
  source_counts: [
    {
      source: 'chrome_history',
      event_count: 233,
      avg_importance: 0.5,
      first_event_at: 1782864000,
      last_event_at: 1783049433,
    },
    {
      source: 'claude_code_agent_history',
      event_count: 34,
      avg_importance: 0.7,
      first_event_at: 1781570000,
      last_event_at: 1781589871,
    },
    {
      source: 'netease_music',
      event_count: 21,
      avg_importance: 0.4,
      first_event_at: 1782510000,
      last_event_at: 1782913076,
    },
  ],
  processing_backlog: { total_pending: 3, all_idle: false },
  deltas: { today: { total_memories: 42, l1_events: 31, l2_assertions: 8, l3_summaries: 3, disk_usage_bytes: null } },
  attention: { pending_assertions: 0, open_circuit_breakers: 0 },
  pending_assertions: { items: [], total: 0, limit: 8, offset: 0 },
};

const sensorPayload = {
  sources: [
    {
      source_name: 'chrome_history',
      plugin_id: 'chrome-history',
      contribution_id: 'chrome_history',
      display_name: 'Chrome History',
      display_name_translated: 'Chrome 历史',
      description: 'Browser history',
      description_translated: '浏览记录会成为可回看的线索',
      icon: 'googlechrome',
      enabled: true,
      status: 'ready',
      running: false,
      last_sync_at: 1783049433,
      last_result_count: 7,
      last_raw_result_count: 18,
      supports_pull_sync: true,
      fields: [],
      current_settings: {},
      sync_mode: 'interval',
      sync_interval_minutes: 30,
      storage_mode: 'local',
      fetch_page_content: false,
      edge_whitelist: [],
    },
    {
      source_name: 'claude_code_agent_history',
      plugin_id: 'coding-agent-history',
      contribution_id: 'claude_code_agent_history',
      display_name: 'Claude Code',
      display_name_translated: 'Claude Code',
      description: 'Coding history',
      description_translated: '代码会话提供工作上下文',
      icon: 'code',
      enabled: true,
      status: 'ready',
      running: false,
      last_sync_at: 1781589871,
      last_result_count: 5,
      supports_pull_sync: true,
      fields: [],
      current_settings: {},
      sync_mode: 'manual',
      sync_interval_minutes: 0,
      storage_mode: 'local',
      fetch_page_content: false,
      edge_whitelist: [],
    },
    {
      source_name: 'photo_library',
      plugin_id: 'photo-library',
      contribution_id: 'photo_library',
      display_name: 'Photos',
      display_name_translated: '照片',
      description: 'Photos',
      description_translated: '照片可以补充地点和时间线',
      icon: 'photo-library',
      enabled: false,
      status: 'setup_required',
      running: false,
      last_sync_at: null,
      supports_pull_sync: true,
      fields: [],
      current_settings: {},
      sync_mode: 'manual',
      sync_interval_minutes: 0,
      storage_mode: 'local',
      fetch_page_content: false,
      edge_whitelist: [],
    },
  ],
};

const todayPayload = {
  date: '2026-07-03',
  weekday: 4,
  sources: [
    {
      source_name: 'chrome_history',
      plugin_id: 'chrome-history',
      display_name: 'Chrome 历史',
      enabled: true,
      count: 36,
      last_event_at: 1783049433,
    },
    {
      source_name: 'netease_music',
      plugin_id: 'netease-music',
      display_name: '网易云音乐',
      enabled: true,
      count: 21,
      last_event_at: 1782913076,
    },
    {
      source_name: 'claude_code_agent_history',
      plugin_id: 'coding-agent-history',
      display_name: 'Claude Code',
      enabled: true,
      count: 0,
      last_event_at: null,
    },
  ],
};

const LocationProbe = () => {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
};

const buildEvent = (index: number, overrides: Record<string, unknown> = {}) => ({
  event_id: `evt-${index}`,
  event_type: 'SENSOR_EVENT',
  source: 'chrome_history',
  timestamp: 1783049000 - index * 60,
  content: `Chrome event ${index}`,
  memory_domain: 'activity',
  retention_class: 'normal',
  importance_score: 0.6,
  cognition_eligible: true,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mockUseInstallableSensors.mockReturnValue({
    items: [{
      plugin_id: 'calendar',
      name: 'Calendar',
      name_i18n: { 'zh-CN': '日历' },
      description: 'Read calendar events',
      description_i18n: { 'zh-CN': '读取日历事件' },
      icon: 'brand:googlecalendar',
      category: 'calendar',
      installed: false,
      rationale: { zh: '', en: '' },
      setup_time_estimate_seconds: 20,
      data_locality: 'local_only',
      surfaces: {
        empty_state: {
          order: 30,
          rationale: { zh: '让 Magi 看到你的日程', en: 'Lets Magi see your schedule' },
        },
      },
    }],
    loading: false,
    error: null,
    refresh: vi.fn(),
  });
  vi.mocked(memoryApi.getDashboard).mockResolvedValue(dashboardPayload as never);
  vi.mocked(sensorsApi.getStatus).mockResolvedValue(sensorPayload as never);
  vi.mocked(sensorsApi.getTodaySummary).mockResolvedValue(todayPayload as never);
  vi.mocked(pluginsApi.updateSettings).mockResolvedValue({} as never);
  useChatShellStore.setState({ activePanel: 'none', settingsNavigationIntent: null });
  usePluginInstallPanelStore.getState().closePanel();
  vi.mocked(memoryApi.getL1Events).mockResolvedValue({
    items: [
      {
        event_id: 'evt-1',
        event_type: 'SENSOR_EVENT',
        source: 'chrome_history',
        timestamp: 1783049000,
        content: 'Chrome 浏览 Opened docs about Magi memory sources',
        memory_domain: 'activity',
        retention_class: 'normal',
        importance_score: 0.6,
        cognition_eligible: true,
        metadata_json: {
          source_facets: [
            { name: 'browser.title', text: 'Opened docs about Magi memory sources' },
            { name: 'browser.domain', text: 'docs.example.com' },
            { name: 'browser.visit_count', numeric: 3 },
          ],
        },
      },
      {
        event_id: 'evt-2',
        event_type: 'SENSOR_EVENT',
        source: 'netease_music',
        timestamp: 1782912000,
        content: 'Played a playlist',
        memory_domain: 'activity',
        retention_class: 'normal',
        importance_score: 0.4,
        cognition_eligible: true,
      },
    ],
    total: 2,
    limit: 500,
    offset: 0,
  } as never);
  vi.mocked(sensorsApi.requestSync).mockResolvedValue({ queued: true, source_name: 'chrome_history' } as never);
});

describe('MemorySourcesPage', () => {
  it('opens the plugin marketplace from a populated source ledger', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/memory/sources']}>
        <Routes>
          <Route path="/memory/sources" element={<MemorySourcesPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('已连接来源')).toBeInTheDocument();
    expect(screen.queryByTestId('memory-sources-empty')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '添加来源' }));
    expect(useChatShellStore.getState()).toMatchObject({
      activePanel: 'settings',
      settingsNavigationIntent: { section: 'pluginsMarketplace' },
    });
    expect(screen.queryByTestId('memory-sources-empty')).not.toBeInTheDocument();
  });

  it('shows source suggestions immediately when empty and refreshes after connection', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      ...dashboardPayload,
      source_counts: [],
      processing_backlog: { total_pending: 0, all_idle: true },
      deltas: {
        ...dashboardPayload.deltas,
        today: { ...dashboardPayload.deltas.today, l1_events: 0 },
      },
    } as never);
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [] } as never);
    vi.mocked(sensorsApi.getTodaySummary).mockResolvedValue({
      ...todayPayload,
      sources: [],
    } as never);
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      items: [],
      total: 0,
      limit: 500,
      offset: 0,
    } as never);

    render(
      <MemoryRouter initialEntries={['/memory/sources']}>
        <Routes>
          <Route path="/memory/sources" element={<MemorySourcesPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByTestId('memory-sources-empty')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '连接第一个来源' })).toBeInTheDocument();
    expect(screen.getByText('把日历、浏览、照片或终端活动接入 Magi，记忆会从这些真实经历中逐渐形成。')).toBeInTheDocument();
    expect(screen.getByText('来源数据只保存在本机。')).toBeInTheDocument();
    expect(screen.getByTestId('source-page-suggestions')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '浏览全部来源' })).toBeInTheDocument();
    expect(screen.queryByTestId('memory-sources-pulse')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '添加来源' })).not.toBeInTheDocument();
    expect(screen.queryByText('已连接来源')).not.toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-calendar')).toBeInTheDocument();

    await user.click(screen.getByTestId('empty-state-connect-calendar'));
    const onDone = usePluginInstallPanelStore.getState().onDone;
    expect(onDone).not.toBeNull();
    act(() => onDone?.({ pluginId: 'calendar', sourceName: 'calendar' }));

    await waitFor(() => expect(memoryApi.getDashboard).toHaveBeenCalledTimes(2));
    expect(sensorsApi.getStatus).toHaveBeenCalledTimes(2);
  });

  it('keeps the pulse visible when work is still waiting despite no source activity', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      ...dashboardPayload,
      source_counts: [],
      processing_backlog: { total_pending: 2, all_idle: false },
      deltas: {
        ...dashboardPayload.deltas,
        today: { ...dashboardPayload.deltas.today, l1_events: 0 },
      },
    } as never);
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({ sources: [] } as never);
    vi.mocked(sensorsApi.getTodaySummary).mockResolvedValue({
      ...todayPayload,
      sources: [],
    } as never);
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      items: [],
      total: 0,
      limit: 500,
      offset: 0,
    } as never);

    render(
      <MemoryRouter initialEntries={['/memory/sources']}>
        <Routes>
          <Route path="/memory/sources" element={<MemorySourcesPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByTestId('memory-sources-pulse')).toBeInTheDocument();
    expect(screen.getByText('今天还没有来源活动；有新内容进入记忆后会显示在这里。')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders the pulse strip and source ledger, then opens a source detail route', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/memory/sources']}>
        <Routes>
          <Route path="/memory/sources" element={<><MemorySourcesPage /><LocationProbe /></>} />
          <Route path="/memory/sources/:sourceName" element={<><MemorySourceDetailPage /><LocationProbe /></>} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('今日脉搏')).toBeInTheDocument();
    expect(screen.getByText('00:00')).toBeInTheDocument();
    expect(screen.getByText('24:00')).toBeInTheDocument();
    expect(screen.getAllByText('异常').length).toBeGreaterThan(0);
    expect(screen.queryByText('今天')).not.toBeInTheDocument();
    expect(screen.queryByText('数据较多')).not.toBeInTheDocument();
    expect(screen.queryByText('无数据')).not.toBeInTheDocument();
    expect(screen.getByText('已连接来源')).toBeInTheDocument();
    expect(screen.getAllByText('Chrome 历史').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Claude Code').length).toBeGreaterThan(0);
    expect(screen.getAllByText('网易云音乐').length).toBeGreaterThan(0);
    expect(screen.getAllByText('照片').length).toBeGreaterThan(0);
    expect(screen.getByTestId('source-pulse-row-chrome_history')).toBeInTheDocument();
    expect(screen.getByTestId('source-pulse-row-netease_music')).toBeInTheDocument();
    expect(screen.queryByTestId('source-pulse-row-claude_code_agent_history')).not.toBeInTheDocument();
    expect(screen.getAllByText('查看')).toHaveLength(4);

    await user.click(screen.getAllByText('查看')[0]);

    expect(await screen.findByTestId('location')).toHaveTextContent('/memory/sources/chrome_history');
    expect(await screen.findByText('最近进入记忆的内容')).toBeInTheDocument();
    expect(screen.getByText('Opened docs about Magi memory sources')).toBeInTheDocument();
  });

  it('loads one source as a full detail page and queues a manual sync', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Chrome 历史')).toBeInTheDocument();
    expect(memoryApi.getL1Events).toHaveBeenCalledWith({ source: 'chrome_history', limit: 50, offset: 0 });
    expect(screen.getByText('36')).toBeInTheDocument();
    expect(screen.getByText('定时同步')).toBeInTheDocument();
    expect(screen.queryByText('interval')).not.toBeInTheDocument();
    expect(screen.getByText('已显示 2 / 共 2 条')).toBeInTheDocument();
    expect(screen.getByTestId('source-detail-facts')).toBeInTheDocument();
    expect(screen.getByText('docs.example.com')).toBeInTheDocument();
    expect(screen.getByText('访问 3 次')).toBeInTheDocument();
    expect(screen.queryByText('Chrome 浏览 Opened docs about Magi memory sources')).not.toBeInTheDocument();
    expect(screen.queryByText('这个来源如何使用')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.sourcesPage.detail.usageTitle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('memory-source-detail-drawer')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '更多操作' }));
    await user.click(screen.getByRole('menuitem', { name: '打开设置' }));

    expect(useChatShellStore.getState().activePanel).toBe('settings');
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({
      section: 'timeline',
      source: 'chrome_history',
    });

    await user.click(screen.getByRole('button', { name: '更多操作' }));
    await user.click(screen.getByRole('menuitem', { name: '暂停' }));

    await waitFor(() => expect(pluginsApi.updateSettings).toHaveBeenCalledWith('chrome-history', {
      'sensors.chrome_history.enabled': false,
    }));

    await user.click(screen.getByRole('button', { name: '同步一次' }));

    await waitFor(() => expect(sensorsApi.requestSync).toHaveBeenCalledWith('chrome_history'));
  });

  it('queues a historical backfill from a source detail page', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Chrome 历史')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '补旧数据' }));
    expect(await screen.findByText('选择 Chrome 历史 要补回的范围。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '开始补回' }));

    await waitFor(() =>
      expect(sensorsApi.requestSync).toHaveBeenCalledWith('chrome_history', {
        mode: 'backfill',
        backfillScope: 'last_30_days',
      })
    );
  });

  it('queues a custom-range historical backfill from a source detail page', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('Chrome 历史')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '补旧数据' }));
    await user.click(await screen.findByRole('radio', { name: '自定义' }));
    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2026-06-01' } });
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-06-30' } });
    await user.click(screen.getByRole('button', { name: '开始补回' }));

    await waitFor(() =>
      expect(sensorsApi.requestSync).toHaveBeenCalledWith('chrome_history', {
        mode: 'backfill',
        backfillScope: 'custom',
        backfillStartDate: '2026-06-01',
        backfillEndDate: '2026-06-30',
      })
    );
  });

  it('keeps an active backfill status and selected range visible', async () => {
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: sensorPayload.sources.map((source) => (
        source.source_name === 'chrome_history'
          ? {
              ...source,
              sync_activity: {
                job_id: 'backfill-job-1',
                mode: 'backfill',
                status: 'queued',
                backfill_scope: 'custom',
                backfill_start_date: '2026-06-01',
                backfill_end_date: '2026-06-30',
              },
            }
          : source
      )),
    } as never);

    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('等待补数据')).toBeInTheDocument();
    expect(screen.getByText('补数据范围：2026-06-01 – 2026-06-30')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '补旧数据' })).toBeDisabled();
  });

  it('keeps a retrying backfill active and shows its attempt count', async () => {
    vi.mocked(sensorsApi.getStatus).mockResolvedValue({
      sources: sensorPayload.sources.map((source) => (
        source.source_name === 'chrome_history'
          ? {
              ...source,
              status: 'retrying',
              sync_activity: {
                job_id: 'backfill-job-retry',
                mode: 'backfill',
                status: 'retrying',
                attempt_count: 2,
                next_attempt_at: 1783049533,
                backfill_scope: 'last_30_days',
                error: 'temporary source failure',
              },
            }
          : source
      )),
    } as never);

    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('补数据重试中（已尝试 2 次）')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '补旧数据' })).toBeDisabled();
  });

  it('polls an active backfill and reports completion', async () => {
    const activePayload = {
      sources: sensorPayload.sources.map((source) => (
        source.source_name === 'chrome_history'
          ? {
              ...source,
              sync_activity: {
                job_id: 'backfill-job-2',
                mode: 'backfill',
                status: 'running',
                backfill_scope: 'last_30_days',
              },
            }
          : source
      )),
    };
    const completedPayload = {
      sources: activePayload.sources.map((source) => (
        source.source_name === 'chrome_history'
          ? {
              ...source,
              sync_activity: {
                job_id: 'backfill-job-2',
                mode: 'backfill',
                status: 'success',
                backfill_scope: 'last_30_days',
              },
            }
          : source
      )),
    };
    vi.mocked(sensorsApi.getStatus)
      .mockResolvedValueOnce(activePayload as never)
      .mockResolvedValue(completedPayload as never);

    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('补数据中')).toBeInTheDocument();
    await waitFor(
      () => expect(toast.success).toHaveBeenCalledWith('Chrome 历史 补数据已完成'),
      { timeout: 2500 },
    );
    expect(await screen.findByText('正常')).toBeInTheDocument();
  });

  it('loads additional source detail events without replacing the first page', async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) => buildEvent(index + 1));
    const secondPage = Array.from({ length: 25 }, (_, index) => buildEvent(index + 51));
    vi.mocked(memoryApi.getL1Events).mockImplementation(async (params) => ({
      items: params?.offset === 50 ? secondPage : firstPage,
      total: 75,
      limit: 50,
      offset: params?.offset ?? 0,
    }) as never);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText('已显示 50 / 共 75 条')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '加载更多' }));

    expect(await screen.findByText('Chrome event 75')).toBeInTheDocument();
    expect(screen.getByText('已显示 75 / 共 75 条')).toBeInTheDocument();
    expect(memoryApi.getL1Events).toHaveBeenCalledWith({ source: 'chrome_history', limit: 50, offset: 50 });
  });

  it('filters source detail events by text and a custom date range', async () => {
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      items: [buildEvent(1, { event_id: 'filtered-1', content: 'Bilibili result' })],
      total: 1,
      limit: 50,
      offset: 0,
    } as never);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/memory/sources/chrome_history']}>
        <Routes>
          <Route path="/memory/sources/:sourceName" element={<MemorySourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByText('最近进入记忆的内容');
    expect(screen.queryByLabelText('全部类型')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '全部' }));
    await user.type(screen.getByLabelText('开始日期'), '2026-07-01');
    await user.type(screen.getByLabelText('结束日期'), '2026-07-03');
    await user.click(screen.getByRole('button', { name: '应用' }));
    await user.type(screen.getByPlaceholderText('搜索内容'), 'bilibili');
    await user.click(screen.getByRole('button', { name: '搜索' }));

    await waitFor(() => expect(memoryApi.getL1Events).toHaveBeenLastCalledWith({
      source: 'chrome_history',
      limit: 50,
      offset: 0,
      start_date: '2026-07-01',
      end_date: '2026-07-03',
      query: 'bilibili',
    }));
    expect(screen.getByText('Bilibili result')).toBeInTheDocument();
  });
});
