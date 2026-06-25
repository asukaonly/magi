import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryGovernancePage } from '@/pages/memory-pages/MemoryGovernancePage';
import { memoryApi } from '@/api/modules/memory';
import { useMemory } from '@/hooks/useMemory';

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
    forgetEpisode: vi.fn(),
    reconsolidateEpisodes: vi.fn(),
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
  loadL0Sessions: vi.fn(),
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
  queryL1Events: vi.fn(),
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
  loadL2Relations: vi.fn(),
  loadL2Assertions: vi.fn(),
  loadL2Entities: vi.fn(),
  loadL2Mentions: vi.fn(),
  loadL2Snapshots: vi.fn(),
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
  loadL3Summaries: vi.fn(),
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
  loadL4Skills: vi.fn(),
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
  vi.mocked(useMemory).mockReturnValue(baseMemoryState as ReturnType<typeof useMemory>);
});

describe('MemoryGovernancePage', () => {
  it('starts from the maintenance workspace without the large page header', async () => {
    renderPage();

    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: '对象明细' })).toBeInTheDocument();
  });

  it('renders object maintenance categories without exposing layer codes', async () => {
    renderPage();
    expect(await screen.findByRole('tab', { name: '对象明细' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: /实体 人物、地点/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /断言 偏好、判断/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /关系图谱/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /实体：用户/ })).toBeInTheDocument();
    expect(screen.queryByText(/\bL[0-4]\b/)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('episode_id')).not.toBeInTheDocument();
  });

  it('uses readable record content in the list and keeps ids in the drawer', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /断言 偏好/ }));

    expect(screen.getByText('内容')).toBeInTheDocument();
    expect(screen.queryByText('ID')).not.toBeInTheDocument();
    expect(screen.queryByText('assert_1')).not.toBeInTheDocument();

    const row = await screen.findByRole('button', { name: /直白/ });
    expect(row).toHaveClass('text-xs');

    await user.click(row);

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).getByText('assert_1')).toBeInTheDocument();
  });

  it('requests the next server page instead of slicing the first loaded rows', async () => {
    const entities = Array.from({ length: 6 }, (_, index) => ({
      entity_id: `ent_page_${index + 1}`,
      canonical_name: `分页实体 ${index + 1}`,
      entity_type: 'person',
      aliases: [],
      updated_at: 1719301200 + index,
    }));
    vi.mocked(useMemory).mockReturnValue({
      ...baseMemoryState,
      l2Entities: entities,
      l2EntitiesTotal: 8,
      l2Assertions: [],
      l2AssertionsTotal: 0,
      l2Relations: [],
      l2RelationsTotal: 0,
      l2Snapshots: [],
      l2SnapshotsTotal: 0,
    } as ReturnType<typeof useMemory>);
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByRole('button', { name: /分页实体 1/ })).toBeInTheDocument();
    expect(screen.getByText('1-6 / 8 条')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '下一页' }));

    await waitFor(() => {
      expect(baseMemoryState.loadL2Entities).toHaveBeenCalledWith({ limit: 6, offset: 6 });
    });
  });

  it('opens record details in a right-side drawer when a row is selected', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByRole('dialog', { name: '记录详情' })).not.toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: /实体：用户/ }));

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(within(drawer).getByText('实体：用户')).toBeInTheDocument();
    expect(within(drawer).getByText('下游影响')).toBeInTheDocument();
    expect(within(drawer).getByText('重新核对这个实体的合并、关系和冲突状态。')).toBeInTheDocument();
    expect(within(drawer).getByRole('button', { name: '重新校准实体' })).toBeEnabled();
    expect(within(drawer).getByRole('button', { name: '删除' })).toBeInTheDocument();
  });

  it('opens a wider drawer and explains raw event re-extraction', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: /原始事件/ }));
    await user.click(await screen.findByRole('button', { name: /用户说自己正在整理记忆页面/ }));

    const drawer = await screen.findByRole('dialog', { name: '记录详情' });
    expect(drawer).toHaveClass('!w-[min(96vw,720px)]');
    expect(drawer).toHaveClass('!max-w-[720px]');

    const action = within(drawer).getByRole('button', { name: '重新抽取结构' });
    expect(action).toBeEnabled();
    expect(within(drawer).getByText('把这条原始事件重新送入结构抽取，更新实体、断言和关系。')).toBeInTheDocument();

    await user.click(action);

    expect(baseMemoryState.replayL2Extraction).toHaveBeenCalledWith('evt_1');
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
