import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryGovernancePage } from '@/pages/memory-pages/MemoryGovernancePage';
import { memoryApi } from '@/api/modules/memory';
import { useMemory } from '@/hooks/useMemory';

const MAGI_CONTEXT_ID = `ctx_project_${'a'.repeat(64)}`;

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const tpl = (opts?.defaultValue as string | undefined) ?? key;
      return tpl.replace(/\{\{(\w+)\}\}/g, (_match, varName) =>
        varName in (opts ?? {}) ? String(opts?.[varName]) : `{{${varName}}}`
      );
    },
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    deleteL1Event: vi.fn(),
    forgetEntity: vi.fn(),
    forgetEpisode: vi.fn(),
    rejectL2Edge: vi.fn(),
    reconsolidateEpisodes: vi.fn(),
    applyCorrection: vi.fn(),
    getCorrectionHistory: vi.fn(),
    getCorrectionContextOptions: vi.fn(),
    revertCorrection: vi.fn(),
    getL2Entities: vi.fn(),
  },
}));

vi.mock('@/hooks/useMemory', () => ({
  useMemory: vi.fn(),
}));

const baseMemoryState = {
  loading: false,
  stats: {
    l0: { active_sessions: 2, total_goals: 3, total_entities: 4, total_tactics: 1 },
    l1: { event_count: 128 },
    l2: { relation_count: 9, assertion_count: 6 },
    l3: { summary_count: 12 },
    l4: { skill_count: 5, open_circuit_breakers: 1 },
    attention: { pending_assertions: 2, open_circuit_breakers: 1 },
  },
  l0Sessions: [
    {
      session_id: 'session_1',
      short_session_id: 's1',
      display_title: '调试会话',
      status: 'active',
      started_at: 1719300000,
      last_active_at: 1719301200,
      goal_count: 1,
      entity_count: 2,
      tactic_count: 1,
    },
  ],
  l0Total: 1,
  l0Workbench: null,
  selectedSessionId: null,
  selectSession: vi.fn(),
  loadL0Sessions: vi.fn().mockResolvedValue(true),
  l1Events: [
    {
      event_id: 'evt_1',
      event_type: 'chat.message',
      source: 'chat',
      timestamp: 1719300000,
      content: '用户说自己正在整理记忆页面。',
      memory_domain: 'conversation',
      retention_class: 'standard',
      importance_score: 0.72,
      cognition_eligible: true,
    },
  ],
  l1Total: 1,
  queryL1Events: vi.fn().mockResolvedValue(true),
  l2Relations: [
    {
      triple_id: 'rel_1',
      subject_id: 'ent_user_8f3e',
      subject_type: 'person',
      predicate: 'USES',
      object_id: 'tool_codex',
      object_type: 'software',
      confidence: 0.9,
      evidence_event_ids: ['evt_1'],
      observation_count: 2,
      status: 'active',
      updated_at: 1719301200,
    },
  ],
  l2RelationsTotal: 1,
  l2Assertions: [
    {
      assertion_id: 'assert_1',
      entity_id: 'ent_user_8f3e',
      entity_type: 'person',
      trait_name: 'communication.response_style.preferred',
      trait_value: '直白',
      confidence_score: 0.82,
      evidence_events: ['evt_1', 'evt_2'],
      validation_state: 'stable',
      volatility_index: 0.1,
      source_domain: 'chat',
      inference_depth: 'explicit',
      first_inferred_at: 1719300000,
      last_validated_at: 1719301200,
      updated_at: 1719301200,
      user_feedback: null,
      user_feedback_at: null,
    },
  ],
  l2AssertionsTotal: 1,
  l2Stats: {
    canonical_self_id: 'user:self',
    relation_count: 1,
    assertion_count: 1,
    identity_link_count: 1,
    extract_skipped: 0,
    extract_by_evidence_class: {},
    skip_by_reason: {},
  },
  identityLinks: [],
  l2Entities: [
    {
      entity_id: 'ent_user_8f3e',
      canonical_name: '用户',
      entity_type: 'person',
      aliases: ['我', '自己'],
      updated_at: 1719301200,
    },
  ],
  l2EntitiesTotal: 1,
  l2Mentions: [],
  l2MentionsTotal: 0,
  l2Snapshots: [],
  l2SnapshotsTotal: 0,
  l2ConflictRules: [],
  l2ActionLoading: false,
  submitManualL2Event: vi.fn(),
  replayL2Extraction: vi.fn(),
  flushL2Microbatches: vi.fn(),
  runL2Reconcile: vi.fn(),
  runL2SnapshotRefresh: vi.fn(),
  upsertL2GraphConflictRule: vi.fn(),
  submitAssertionFeedback: vi.fn(),
  correctAssertion: vi.fn(),
  loadL2Relations: vi.fn().mockResolvedValue(true),
  loadL2Assertions: vi.fn().mockResolvedValue(true),
  loadL2Entities: vi.fn().mockResolvedValue(true),
  loadL2Mentions: vi.fn(),
  loadL2Snapshots: vi.fn().mockResolvedValue(true),
  l3Summaries: [
    {
      summary_id: 'sum_1',
      summary_type: 'periodic',
      summary_category: 'day',
      period_start: 1719290000,
      period_end: 1719300000,
      content: '今天主要在整理记忆维护页。',
      key_topics: ['memory'],
      source_event_count: 4,
      created_at: 1719300000,
    },
  ],
  l3Total: 1,
  loadL3Summaries: vi.fn().mockResolvedValue(true),
  l4Skills: [
    {
      skill_id: 'skill_1',
      skill_name: '按测试修页面',
      skill_category: 'frontend',
      proficiency: 0.74,
      success_rate: 0.8,
      total_attempts: 5,
      success_count: 4,
      failure_count: 1,
      circuit_breaker_state: 'closed',
      last_used_at: 1719300000,
    },
  ],
  l4Total: 1,
  loadL4Skills: vi.fn().mockResolvedValue(true),
  searchQuery: '',
  setSearchQuery: vi.fn(),
  searchResults: {
    l0_workbench: [],
    l1_events: [],
    l1_evidence_bundles: [],
    l1_timeline_summary: [],
    l2_entity_cards: [],
    l2_relationships: [],
    l2_assertions: [],
    l2_episodes: [],
    l2_experiences: [],
    l2_state_facts: [],
    l2_state_history: [],
    l3_reflections: [],
    l4_procedures: [],
    structured_results: [],
    trace: {},
  },
  searching: false,
  handleSearch: vi.fn(),
  clearDialogOpen: false,
  setClearDialogOpen: vi.fn(),
  clearing: false,
  handleClearRequest: vi.fn(),
  handleClearConfirm: vi.fn(),
  refresh: vi.fn(),
  refreshAll: vi.fn(),
};

const renderPage = () => render(
  <MemoryRouter>
    <MemoryGovernancePage />
  </MemoryRouter>
);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryApi.getCorrectionContextOptions).mockResolvedValue({
    items: [{
      context_id: MAGI_CONTEXT_ID,
      dimension: 'project',
      label: 'Magi',
    }],
  });
  vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
    target: { kind: 'assertion', id: 'assert_1' },
    versions: [],
    corrections: [],
    context_labels: {},
  });
  vi.mocked(memoryApi.getL2Entities).mockResolvedValue({
    items: [],
    total: 0,
    limit: 100,
    offset: 0,
  });
  vi.mocked(useMemory).mockReturnValue(baseMemoryState as ReturnType<typeof useMemory>);
});

const renderRelationshipCorrection = async (user: ReturnType<typeof userEvent.setup>) => {
  vi.mocked(useMemory).mockReturnValue({
    ...baseMemoryState,
    l2Entities: [
      ...baseMemoryState.l2Entities,
      { entity_id: 'tool_codex', canonical_name: 'Codex', entity_type: 'software', aliases: [] },
      { entity_id: 'tool_magi', canonical_name: 'Magi', entity_type: 'software', aliases: [] },
    ],
  } as ReturnType<typeof useMemory>);
  vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
    target: { kind: 'edge', id: 'rel_1' },
    versions: [],
    corrections: [],
    context_labels: {},
  });

  renderPage();
  await user.click(screen.getByRole('button', { name: /关系图谱/ }));
  await user.click(await screen.findByRole('button', { name: /^打开记录 用户 使用 Codex$/i }));
  const drawer = await screen.findByRole('dialog', { name: '记录详情' });
  await user.click(within(drawer).getByRole('button', { name: '修正这条记忆' }));
  return screen.findByRole('dialog', { name: '修正这条记忆' });
};

describe('MemoryGovernancePage', () => {
  it('starts with streamlined navigation and compact status summary', async () => {
    renderPage();

    expect(screen.getByRole('heading', { level: 1, name: '记忆管理' })).toHaveClass('sr-only');
    expect(screen.queryByText('按记忆对象查看、整理、遗忘和诊断。')).not.toBeInTheDocument();
    const status = screen.getByTestId('governance-status-summary');
    expect(within(status).getByText('需要处理')).toBeInTheDocument();
    expect(within(status).getByText('2 条待处理')).toBeInTheDocument();
    expect(within(status).getByText('1 个工具异常')).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: '对象明细' })).toBeInTheDocument();
  });

  it('renders object maintenance categories without exposing layer codes', async () => {
    renderPage();
    expect(await screen.findByRole('tab', { name: '对象明细' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: /实体 人物、地点/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /断言 偏好、判断/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /关系图谱/ })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /^打开记录 用户$/ })).toBeInTheDocument();
    expect(screen.queryByText('健康')).not.toBeInTheDocument();
    expect(screen.queryByText('稳定')).not.toBeInTheDocument();
    expect(screen.queryByText(/\bL[0-4]\b/)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('episode_id')).not.toBeInTheDocument();
  });

  it('shows an old assertion as historical without offering another correction', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Assertions: [{
        ...baseMemoryState.l2Assertions[0],
        status: 'user_rejected',
        validation_state: 'stable',
      }],
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    const recordButton = await screen.findByRole('button', { name: /直白/ });
    expect(recordButton).toHaveTextContent('已否定');
    await user.click(recordButton);

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).queryByRole('button', { name: '修正这条记忆' })).not.toBeInTheDocument();
    expect(within(drawer).getByText('这是历史记录，可查看修正历史或撤销最新修正。')).toBeInTheDocument();
    expect(memoryApi.getCorrectionHistory).toHaveBeenCalledWith('assertion', 'assert_1');
  });

  it('shows an invalidated assertion as historical without offering another correction', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Assertions: [{
        ...baseMemoryState.l2Assertions[0],
        status: 'invalidated',
        validation_state: 'stable',
      }],
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    const recordButton = await screen.findByRole('button', { name: /直白/ });
    expect(recordButton).toHaveTextContent('已失效');
    await user.click(recordButton);

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).queryByRole('button', { name: '修正这条记忆' })).not.toBeInTheDocument();
    expect(within(drawer).getByText('这是历史记录，可查看修正历史或撤销最新修正。')).toBeInTheDocument();
  });

  it('keeps an old relationship available for history without offering correction', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Relations: [{
        ...baseMemoryState.l2Relations[0],
        status: 'deprecated',
      }],
    } as ReturnType<typeof useMemory>);
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'edge', id: 'rel_1' },
      versions: [],
      corrections: [],
      context_labels: {},
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /关系图谱/ }));
    const recordButton = await screen.findByRole('button', { name: /^打开记录 用户 使用 Codex$/i });
    expect(recordButton).toHaveTextContent('已替代');
    await user.click(recordButton);

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).queryByRole('button', { name: '修正这条记忆' })).not.toBeInTheDocument();
    expect(within(drawer).getByText('这是历史记录，可查看修正历史或撤销最新修正。')).toBeInTheDocument();
    expect(memoryApi.getCorrectionHistory).toHaveBeenCalledWith('edge', 'rel_1');
  });

  it('localizes a conflicted relationship and keeps it read-only', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Relations: [{
        ...baseMemoryState.l2Relations[0],
        status: 'conflicted',
      }],
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /关系图谱/ }));
    const recordButton = await screen.findByRole('button', { name: /^打开记录 用户 使用 Codex$/i });
    expect(recordButton).toHaveTextContent('有冲突');
    await user.click(recordButton);

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).queryByRole('button', { name: '修正这条记忆' })).not.toBeInTheDocument();
  });

  it('turns an empty object category into a useful next step', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Entities: [],
      l2EntitiesTotal: 0,
    } as ReturnType<typeof useMemory>);

    renderPage();

    expect(await screen.findByRole('heading', { level: 3, name: '还没有实体记录' })).toBeInTheDocument();
    expect(screen.getByText('Magi 会从对话和已连接的来源中逐步整理这类记忆。')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '添加来源' })).toHaveAttribute('href', '/memory/sources');
    expect(screen.getByRole('link', { name: '开始对话' })).toHaveAttribute('href', '/chat');
    expect(screen.queryByRole('searchbox', { name: '搜索当前选项记录' })).not.toBeInTheDocument();
  });

  it('requests global object search for the active category', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Relations: [
        baseMemoryState.l2Relations[0],
        {
          triple_id: 'rel_2',
          subject_id: 'ent_user_8f3e',
          subject_type: 'person',
          predicate: 'VISITED',
          object_id: 'place:huzhou',
          object_type: 'place',
          confidence: 0.76,
          evidence_event_ids: ['evt_2'],
          observation_count: 1,
          status: 'active',
          updated_at: 1719301400,
        },
      ],
      l2RelationsTotal: 42,
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /关系图谱/ }));

    const search = await screen.findByRole('searchbox', { name: '搜索当前选项记录' });
    await user.type(search, 'codex');

    expect(await screen.findByRole('button', { name: /^打开记录 用户 使用 codex$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^打开记录 用户 去过 huzhou$/ })).toBeInTheDocument();

    await waitFor(() => {
      expect(baseMemoryState.loadL2Relations).toHaveBeenLastCalledWith({ limit: 20, offset: 0, query: 'codex', include_inactive: true });
    });

    await user.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => {
      expect(baseMemoryState.loadL2Relations).toHaveBeenLastCalledWith({ limit: 20, offset: 20, query: 'codex', include_inactive: true });
    });

    await user.clear(search);
    await waitFor(() => {
      expect(baseMemoryState.loadL2Relations).toHaveBeenLastCalledWith({ limit: 20, offset: 0, include_inactive: true });
    });
  });

  it('waits for IME composition before searching object records', async () => {
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /关系图谱/ }));

    const search = await screen.findByRole('searchbox', { name: '搜索当前选项记录' });
    baseMemoryState.loadL2Relations.mockClear();

    fireEvent.compositionStart(search);
    fireEvent.change(search, { target: { value: 'm' } });
    fireEvent.change(search, { target: { value: '梅' } });

    expect(search).toHaveValue('梅');
    expect(baseMemoryState.loadL2Relations).not.toHaveBeenCalled();

    fireEvent.compositionEnd(search);

    await waitFor(() => {
      expect(baseMemoryState.loadL2Relations).toHaveBeenLastCalledWith({ limit: 20, offset: 0, query: '梅', include_inactive: true });
    });
  });

  it('uses readable record content in the list and keeps ids in the drawer', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));

    expect(screen.getByText('内容')).toBeInTheDocument();
    expect(screen.queryByText('ID')).not.toBeInTheDocument();
    expect(screen.queryByText('assert_1')).not.toBeInTheDocument();

    const row = await screen.findByRole('button', { name: /^打开记录 用户的沟通风格偏好是直白$/ });
    expect(row).toHaveClass('text-xs');
    expect(screen.queryByRole('button', { name: /^打开记录 直白$/ })).not.toBeInTheDocument();

    await user.click(row);

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).getByText('assert_1')).toBeInTheDocument();
    const internalSummary = within(drawer).getByText('内部信息').closest('summary');
    expect(internalSummary).not.toBeNull();
    const internalDetails = internalSummary?.closest('details');
    expect(internalDetails).not.toHaveAttribute('open');
    await user.click(internalSummary as HTMLElement);
    expect(internalDetails).toHaveAttribute('open');
  });

  it('uses category-specific columns and readable relation statements', async () => {
    const user = userEvent.setup();
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Relations: [
        ...baseMemoryState.l2Relations,
        {
          ...baseMemoryState.l2Relations[0],
          triple_id: 'rel_viewed',
          subject_id: 'user:self',
          subject_type: 'user',
          predicate: 'viewed',
          object_id: 'other_google_com',
          object_type: 'other',
        },
      ],
      l2RelationsTotal: 2,
    } as ReturnType<typeof useMemory>);
    renderPage();

    expect(await screen.findByText('对象类型')).toBeInTheDocument();
    expect(screen.getByText('当前关联')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /原始事件/ }));
    expect(await screen.findByText('事件类型')).toBeInTheDocument();
    expect(screen.getByText('发生时间')).toBeInTheDocument();
    expect(screen.getAllByText('对话消息')).toHaveLength(2);
    expect(screen.getByText('对话')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /关系图谱/ }));
    expect(await screen.findByRole('button', { name: /^打开记录 用户 使用 codex$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^打开记录 用户 浏览了 google com$/ })).toBeInTheDocument();
    expect(screen.queryByText(/ent_user_8f3e USES tool_codex/)).not.toBeInTheDocument();
    expect(screen.queryByText(/viewed other/)).not.toBeInTheDocument();
    expect(screen.getAllByText('用户 → 其他')).toHaveLength(2);
    expect(screen.getByText('观察')).toBeInTheDocument();
  });

  it('shows a visible load error and retries the active category', async () => {
    const loadL2Entities = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      loadL2Entities,
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取这类记录，请稍后重试。');
    await user.click(screen.getByRole('button', { name: '重新读取' }));

    await waitFor(() => expect(loadL2Entities).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('button', { name: /^打开记录 用户$/ })).toBeInTheDocument();
  });

  it('collapses keyed assertion traits into readable relation labels', async () => {
    const user = userEvent.setup();
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Assertions: [
        {
          ...baseMemoryState.l2Assertions[0],
          assertion_id: 'assert_tool',
          entity_id: 'user:self',
          trait_name: 'tool.dev-tauri-hot_sh-75135f',
          trait_value: 'dev tauri hot sh',
        },
      ],
      l2Entities: [
        {
          entity_id: 'user:self',
          canonical_name: '用户',
          entity_type: 'person',
          aliases: [],
        },
      ],
    } as ReturnType<typeof useMemory>);

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));

    expect(await screen.findByRole('button', { name: /^打开记录 用户的工具是dev tauri hot sh$/ })).toBeInTheDocument();
    expect(screen.queryByText(/tool\.dev-tauri-hot_sh/)).not.toBeInTheDocument();
  });

  it('requests the next server page instead of slicing the first loaded rows', async () => {
    const entities = Array.from({ length: 20 }, (_, index) => ({
      entity_id: `ent_page_${index + 1}`,
      canonical_name: `分页实体 ${index + 1}`,
      entity_type: 'person',
      aliases: [],
      updated_at: 1719301200 + index,
    }));
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Entities: entities,
      l2EntitiesTotal: 24,
      l2Assertions: [],
      l2AssertionsTotal: 0,
      l2Relations: [],
      l2RelationsTotal: 0,
      l2Snapshots: [],
      l2SnapshotsTotal: 0,
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByRole('button', { name: /^打开记录 分页实体 1$/ })).toBeInTheDocument();
    expect(screen.getByText('1-20 / 24 条')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '下一页' }));

    await waitFor(() => {
      expect(baseMemoryState.loadL2Entities).toHaveBeenCalledWith({ limit: 20, offset: 20 });
    });
  });

  it('opens record details in a right-side drawer when a row is selected', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByRole('dialog', { name: '记录详情' })).not.toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: /^打开记录 用户$/ }));

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).getByRole('heading', { name: '用户' })).toBeInTheDocument();
    expect(within(drawer).getByText('当前可见关联')).toBeInTheDocument();
    expect(within(drawer).getByText('这里只反映当前已读取的数据，不代表删除或遗忘的完整影响范围。')).toBeInTheDocument();
    expect(within(drawer).getByText('重新核对这个实体的合并、关系和冲突状态。')).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: '重新核对' })).toBeEnabled();
    expect(within(drawer).getByRole('button', { name: '遗忘实体及相关知识' })).toBeEnabled();
    expect(within(drawer).queryByRole('button', { name: '删除原始事件' })).not.toBeInTheDocument();
  });

  it('opens a wider drawer and explains raw event re-extraction', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /原始事件/ }));
    await user.click(await screen.findByRole('button', { name: /用户说自己正在整理记忆页面/ }));

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(drawer).toHaveClass('!w-[min(96vw,760px)]');
    expect(drawer).toHaveClass('!max-w-[760px]');

    const action = within(drawer).getByRole('button', { name: '重新提取' });
    expect(action).toBeEnabled();
    expect(within(drawer).getByText('把这条原始事件重新送入结构抽取，更新实体、断言和关系。')).toBeInTheDocument();

    await user.click(action);

    expect(baseMemoryState.replayL2Extraction).toHaveBeenCalledWith('evt_1');
  });

  it('enables supported maintenance actions from the drawer', async () => {
    vi.mocked(memoryApi.deleteL1Event).mockResolvedValue({ event_id: 'evt_1', deleted: true });
    vi.mocked(memoryApi.forgetEntity).mockResolvedValue({ l2_counts: { entities: 1 }, l1_events_deleted: 0 });
    const user = userEvent.setup();

    renderPage();

    await user.click(screen.getByRole('button', { name: /原始事件/ }));
    await user.click(await screen.findByRole('button', { name: /用户说自己正在整理记忆页面/ }));
    const eventDrawer = await screen.findByRole('dialog', { name: '记录详情' });
    const deleteButton = within(eventDrawer).getByRole('button', { name: '删除原始事件' });
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);
    await waitFor(() => {
      expect(memoryApi.deleteL1Event).toHaveBeenCalledWith('evt_1');
    });
    expect(baseMemoryState.queryL1Events).toHaveBeenCalledWith({ limit: 20, offset: 0 });

    await user.click(screen.getByRole('button', { name: /实体 人物/ }));
    await user.click(await screen.findByRole('button', { name: /^打开记录 用户$/ }));
    const entityDrawer = await screen.findByRole('dialog', { name: '记录详情' });
    const cascadeButton = within(entityDrawer).getByRole('button', { name: '遗忘实体及相关知识' });
    expect(cascadeButton).toBeEnabled();
    await user.click(cascadeButton);
    await waitFor(() => {
      expect(memoryApi.forgetEntity).toHaveBeenCalledWith('ent_user_8f3e', false);
    });
    expect(baseMemoryState.loadL2Entities).toHaveBeenCalledWith({ limit: 20, offset: 0 });
  });

  it('removes an incorrect assertion through the governed correction flow', async () => {
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_1',
        request_id: 'request_1',
        actor_id: 'user:self',
        target_kind: 'assertion',
        target_id: 'assert_1',
        slot_key: 'slot_1',
        claim_fingerprint: 'claim_1',
        correction_kind: 'record_error',
        before: { trait_value: '直白' },
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: { trait_value: '直白', status: 'user_rejected' },
      derivation_state: 'completed',
      created: true,
    });
    const user = userEvent.setup();

    renderPage();

    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    await user.click(await screen.findByRole('button', { name: /直白/ }));
    const assertionDrawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(await within(assertionDrawer).findByText('还没有修正过这条记忆。')).toBeInTheDocument();
    await user.click(within(assertionDrawer).getByRole('button', { name: '修正这条记忆' }));

    const correctionDialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.click(within(correctionDialog).getByRole('button', { name: /这条记忆不存在/ }));
    await user.click(within(correctionDialog).getByRole('button', { name: '确认不再使用' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'assertion', id: 'assert_1' },
      correction_kind: 'record_error',
      expected_updated_at: 1719301200,
    }));
    expect(vi.mocked(memoryApi.applyCorrection).mock.calls[0][0]).not.toHaveProperty('replacement');
    expect(await within(correctionDialog).findByText('已经按你的意思修正')).toBeInTheDocument();
    expect(within(correctionDialog).getByText('之后不会再把原来的内容当作你的信息。')).toBeInTheDocument();

    await user.click(within(correctionDialog).getByRole('button', { name: '完成' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '记录详情' })).not.toBeInTheDocument());
    expect(baseMemoryState.loadL2Assertions).toHaveBeenCalledWith({ limit: 20, offset: 0, include_inactive: true });
  });

  it('records a changed assertion with its effective time and keeps failed input', async () => {
    vi.mocked(memoryApi.applyCorrection)
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce({
        correction: {
          correction_id: 'correction_2',
          request_id: 'request_2',
          actor_id: 'user:self',
          target_kind: 'assertion',
          target_id: 'assert_1',
          slot_key: 'slot_1',
          claim_fingerprint: 'claim_1',
          correction_kind: 'situation_changed',
          before: { trait_value: '直白' },
          replacement: { value: '详细一些' },
          replacement_target_id: 'assert_2',
          effective_at: Math.floor(new Date('2099-06-26T12:00').getTime() / 1000),
          created_at: 1719374400,
          state: 'active',
        },
        current_claim: { trait_value: '详细一些' },
        derivation_state: 'pending',
        created: true,
      });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    await user.click(await screen.findByRole('button', { name: /直白/ }));
    await user.click(within(await screen.findByRole('dialog', { name: '记录详情' })).getByRole('button', { name: '修正这条记忆' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });

    await user.click(within(dialog).getByRole('button', { name: /以前是这样，现在变了/ }));
    const valueInput = within(dialog).getByLabelText('正确内容');
    await user.clear(valueInput);
    await user.type(valueInput, '详细一些');
    fireEvent.change(within(dialog).getByLabelText('从什么时候开始变化？'), {
      target: { value: '2099-06-26T12:00' },
    });
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('你填写的内容还在');
    expect(valueInput).toHaveValue('详细一些');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(2));
    expect(memoryApi.applyCorrection).toHaveBeenLastCalledWith(expect.objectContaining({
      target: { kind: 'assertion', id: 'assert_1' },
      correction_kind: 'situation_changed',
      replacement: { value: '详细一些' },
      effective_at: Math.floor(new Date('2099-06-26T12:00').getTime() / 1000),
      expected_updated_at: 1719301200,
    }));
    expect(await within(dialog).findByText('详细一些')).toBeInTheDocument();
    expect(within(dialog).getByText('到设定时间后，相关总结会自动更新。')).toBeInTheDocument();
    expect(within(dialog).queryByText('相关总结会在后台继续更新，不影响这次修正生效。')).not.toBeInTheDocument();
  });

  it('corrects a relationship object without exposing internal identifiers', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Entities: [
        ...baseMemoryState.l2Entities,
        { entity_id: 'tool_codex', canonical_name: 'Codex', entity_type: 'software', aliases: [] },
        { entity_id: 'tool_magi', canonical_name: 'Magi', entity_type: 'software', aliases: [] },
      ],
    } as ReturnType<typeof useMemory>);
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'edge', id: 'rel_1' },
      versions: [],
      corrections: [],
      context_labels: {},
    });
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_edge',
        request_id: 'request_edge',
        actor_id: 'user:self',
        target_kind: 'edge',
        target_id: 'rel_1',
        slot_key: 'slot_edge',
        claim_fingerprint: 'claim_edge',
        correction_kind: 'record_error',
        before: { object_id: 'tool_codex' },
        replacement: { object_id: 'tool_magi', object_type: 'software' },
        replacement_target_id: 'rel_2',
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: { object_id: 'tool_magi' },
      derivation_state: 'completed',
      created: true,
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /关系图谱/ }));
    await user.click(await screen.findByRole('button', { name: /^打开记录 用户 使用 Codex$/i }));
    const relationDrawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(relationDrawer).queryByText('tool_codex')).not.toBeInTheDocument();
    await user.click(within(relationDrawer).getByRole('button', { name: '修正这条记忆' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    await user.selectOptions(within(dialog).getByLabelText('正确的关系对象'), 'tool_magi');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'edge', id: 'rel_1' },
      correction_kind: 'record_error',
      replacement: { object_id: 'tool_magi', object_type: 'software' },
      expected_updated_at: 1719301200,
    }));
    expect(await within(dialog).findByText('用户 使用 Magi')).toBeInTheDocument();
  });

  it('limits an assertion to a workspace project chosen on the memory page', async () => {
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_scope_assertion',
        request_id: 'request_scope_assertion',
        actor_id: 'user:self',
        target_kind: 'assertion',
        target_id: 'assert_1',
        slot_key: 'slot_1',
        claim_fingerprint: 'claim_1',
        correction_kind: 'scope_refinement',
        before: { trait_value: '直白' },
        replacement: { value: '直白' },
        replacement_target_id: 'assert_scope',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: {
        trait_value: '直白',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      },
      derivation_state: 'completed',
      created: true,
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    await user.click(await screen.findByRole('button', { name: /直白/ }));
    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    await user.click(within(drawer).getByRole('button', { name: '修正这条记忆' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });

    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    await user.selectOptions(await within(dialog).findByLabelText('选择项目'), MAGI_CONTEXT_ID);
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'assertion', id: 'assert_1' },
      correction_kind: 'scope_refinement',
      replacement: { value: '直白' },
      scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      expected_updated_at: 1719301200,
    }));
  });

  it('limits a relationship to a workspace project chosen on the memory page', async () => {
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_scope_edge',
        request_id: 'request_scope_edge',
        actor_id: 'user:self',
        target_kind: 'edge',
        target_id: 'rel_1',
        slot_key: 'slot_edge',
        claim_fingerprint: 'claim_edge',
        correction_kind: 'scope_refinement',
        before: { object_id: 'tool_codex' },
        replacement: {},
        replacement_target_id: 'rel_1',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: {
        object_id: 'tool_codex',
        scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      },
      derivation_state: 'completed',
      created: true,
    });
    const user = userEvent.setup();
    const dialog = await renderRelationshipCorrection(user);

    await user.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    await user.selectOptions(await within(dialog).findByLabelText('选择项目'), MAGI_CONTEXT_ID);
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'edge', id: 'rel_1' },
      correction_kind: 'scope_refinement',
      replacement: {},
      scope: { all_of: [{ dimension: 'project', context_id: MAGI_CONTEXT_ID }] },
      expected_updated_at: 1719301200,
    }));
  });

  it('records when a relationship changed and what replaced it', async () => {
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_changed_edge',
        request_id: 'request_changed_edge',
        actor_id: 'user:self',
        target_kind: 'edge',
        target_id: 'rel_1',
        slot_key: 'slot_edge',
        claim_fingerprint: 'claim_edge',
        correction_kind: 'situation_changed',
        before: { object_id: 'tool_codex' },
        replacement: { object_id: 'tool_magi', object_type: 'software' },
        replacement_target_id: 'rel_2',
        effective_at: 1719374400,
        created_at: 1719374400,
        state: 'active',
      },
      current_claim: { object_id: 'tool_magi' },
      derivation_state: 'completed',
      created: true,
    });
    const user = userEvent.setup();
    const dialog = await renderRelationshipCorrection(user);

    await user.click(within(dialog).getByRole('button', { name: /以前是这样，现在变了/ }));
    await user.selectOptions(within(dialog).getByLabelText('正确的关系对象'), 'tool_magi');
    fireEvent.change(within(dialog).getByLabelText('从什么时候开始变化？'), {
      target: { value: '2024-06-26T12:00' },
    });
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'edge', id: 'rel_1' },
      correction_kind: 'situation_changed',
      replacement: { object_id: 'tool_magi', object_type: 'software' },
      effective_at: Math.floor(new Date('2024-06-26T12:00').getTime() / 1000),
      expected_updated_at: 1719301200,
    }));
  });

  it('removes a relationship only after explicit confirmation', async () => {
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_remove_edge',
        request_id: 'request_remove_edge',
        actor_id: 'user:self',
        target_kind: 'edge',
        target_id: 'rel_1',
        slot_key: 'slot_edge',
        claim_fingerprint: 'claim_edge',
        correction_kind: 'record_error',
        before: { object_id: 'tool_codex' },
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: null,
      derivation_state: 'completed',
      created: true,
    });
    const user = userEvent.setup();
    const dialog = await renderRelationshipCorrection(user);

    await user.click(within(dialog).getByRole('button', { name: /这段关系不存在/ }));
    expect(memoryApi.applyCorrection).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole('button', { name: '确认不再使用' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    const request = vi.mocked(memoryApi.applyCorrection).mock.calls[0][0];
    expect(request).toMatchObject({
      target: { kind: 'edge', id: 'rel_1' },
      correction_kind: 'record_error',
      expected_updated_at: 1719301200,
    });
    expect(request).not.toHaveProperty('replacement');
  });

  it.each([404, 409])('does not overwrite a memory after an HTTP %s response', async (status) => {
    vi.mocked(memoryApi.applyCorrection).mockRejectedValue({
      isAxiosError: true,
      message: 'Target changed',
      response: {
        status,
        data: { detail: status === 404 ? 'Correction target not found' : 'Assertion changed after it was loaded' },
      },
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    await user.click(await screen.findByRole('button', { name: /直白/ }));
    await user.click(within(await screen.findByRole('dialog', { name: '记录详情' })).getByRole('button', { name: '修正这条记忆' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    const input = within(dialog).getByLabelText('正确内容');
    await user.clear(input);
    await user.type(input, '更简洁');
    await user.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('当前内容不会被覆盖');
    expect(input).toHaveValue('更简洁');
    expect(within(dialog).queryByRole('button', { name: '保存修正' })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: '查看最新内容' }));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '记录详情' })).not.toBeInTheDocument());
    expect(baseMemoryState.loadL2Assertions).toHaveBeenCalledWith({ limit: 20, offset: 0, include_inactive: true });
  });

  it('shows correction history and only reverts the latest active correction after confirmation', async () => {
    vi.mocked(memoryApi.getCorrectionHistory).mockResolvedValue({
      target: { kind: 'assertion', id: 'assert_1' },
      versions: [
        { assertion_id: 'assert_1', trait_value: '直白', status: 'user_rejected', valid_from: 1719300000, valid_to: 1719301300 },
        { assertion_id: 'assert_2', trait_value: '详细一些', status: 'active', valid_from: 1719301300 },
      ],
      corrections: [
        {
          correction_id: 'correction_old',
          request_id: 'request_old',
          actor_id: 'user:self',
          target_kind: 'assertion',
          target_id: 'assert_1',
          slot_key: 'slot_1',
          claim_fingerprint: 'claim_1',
          correction_kind: 'record_error',
          before: { trait_value: '旧内容' },
          replacement: { value: '直白' },
          created_at: 1719301200,
          state: 'active',
        },
        {
          correction_id: 'correction_latest',
          request_id: 'request_latest',
          actor_id: 'user:self',
          target_kind: 'assertion',
          target_id: 'assert_1',
          slot_key: 'slot_1',
          claim_fingerprint: 'claim_1',
          correction_kind: 'situation_changed',
          before: { trait_value: '直白' },
          replacement: { value: '详细一些' },
          created_at: 1719301300,
          state: 'active',
        },
      ],
      context_labels: {},
    });
    vi.mocked(memoryApi.revertCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction_latest',
        request_id: 'request_latest',
        actor_id: 'user:self',
        target_kind: 'assertion',
        target_id: 'assert_1',
        slot_key: 'slot_1',
        claim_fingerprint: 'claim_1',
        correction_kind: 'situation_changed',
        before: { trait_value: '直白' },
        created_at: 1719301300,
        state: 'reverted',
      },
      current_claim: { trait_value: '直白' },
      derivation_state: 'pending',
      created: false,
    });
    const user = userEvent.setup();

    renderPage();
    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));
    await user.click(await screen.findByRole('button', { name: /直白/ }));
    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(await within(drawer).findByText('2 次')).toBeInTheDocument();
    expect(within(drawer).getAllByRole('button', { name: '撤销这次修正' })).toHaveLength(1);
    await user.click(within(drawer).getByRole('button', { name: '撤销这次修正' }));
    expect(within(drawer).getByText('撤销后会恢复到这次修正之前的理解。')).toBeInTheDocument();
    await user.click(within(drawer).getByRole('button', { name: '确认撤销' }));

    await waitFor(() => expect(memoryApi.revertCorrection).toHaveBeenCalledWith(
      'correction_latest',
      expect.any(String)
    ));
  });

  it('keeps manual chapter consolidation available', async () => {
    vi.mocked(memoryApi.reconsolidateEpisodes).mockResolvedValue({
      promoted: 3, standouts: 2, merged: 0, invalidated: 0,
      summaries_generated: 2, summary_errors: [],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('tab', { name: '手动整理' }));
    await user.click(await screen.findByRole('button', { name: '立即整理章节' }));

    await waitFor(() => {
      expect(screen.getByText(/升级 3 条/)).toBeInTheDocument();
    });
    expect(memoryApi.reconsolidateEpisodes).toHaveBeenCalled();
  });

  it('renders when memory payloads are only partially populated', async () => {
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      stats: {
        l0: {},
        l1: {},
        l2: {},
        l3: {},
        attention: {},
      },
      l0Sessions: [
        {
          session_id: 'session_sparse',
          short_session_id: '',
          display_title: '',
        },
      ],
      l1Events: [
        {
          event_id: 'evt_sparse',
          event_type: 'chat.message',
          timestamp: 1719300000,
          content: '',
          memory_domain: 'conversation',
          retention_class: 'standard',
        },
      ],
      l2Relations: [
        {
          triple_id: 'rel_sparse',
          subject_id: 'ent_sparse',
          subject_type: 'person',
          predicate: 'USES',
          object_id: 'tool_sparse',
          object_type: 'software',
        },
      ],
      l2Assertions: [
        {
          assertion_id: 'assert_sparse',
          entity_id: 'ent_sparse',
          entity_type: 'person',
          trait_name: 'preference',
          trait_value: '',
        },
      ],
      l2Entities: [
        {
          entity_id: 'ent_sparse',
          canonical_name: 'Sparse entity',
          entity_type: 'person',
        },
      ],
      l3Summaries: [
        {
          summary_id: 'sum_sparse',
          summary_type: 'periodic',
          summary_category: 'day',
          period_start: 1719290000,
          period_end: 1719300000,
          content: '',
          created_at: 1719300000,
        },
      ],
      l4Skills: [
        {
          skill_id: 'skill_sparse',
          skill_name: '',
          skill_category: 'frontend',
        },
      ],
    } as unknown as ReturnType<typeof useMemory>);

    renderPage();

    expect(await screen.findByRole('tab', { name: '对象明细' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sparse entity/ })).toBeInTheDocument();
  });
});
