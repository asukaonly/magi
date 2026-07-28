import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { MemoryPortraitPage } from '@/pages/memory-pages/MemoryPortraitPage';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import { memoryApi } from '@/api/modules/memory';
import { profileApi } from '@/api/modules/profile';
import { manualEntriesApi } from '@/api/modules/manualEntries';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.portrait.title': '画像',
    'memory.portrait.subtitle': 'Magi 眼中的你',
    'memory.portrait.loading': '正在读取关于你的内容…',
    'memory.portrait.loadFailed.title': '暂时没能读取关于你的内容',
    'memory.portrait.loadFailed.body': '已有内容没有丢失，请稍后再试。',
    'memory.portrait.loadFailed.retry': '重新读取',
    'memory.portrait.world.summaryTitle': 'Magi 目前这样理解你',
    'memory.portrait.world.meta': '已形成 {{count}} 条理解',
    'memory.portrait.world.inspectItems': '查看并修正 {{count}} 条具体记忆',
    'memory.portrait.world.correct': '修正',
    'memory.portrait.world.correctItem': '修正 {{value}}',
    'memory.portrait.world.groups.identity': '身份信息',
    'memory.portrait.world.groups.projects': '长期项目',
    'memory.portrait.world.groups.preferences': '偏好与关注',
    'memory.portrait.world.groups.work_style': '协作方式',
    'memory.portrait.empty.title': '还在认识你',
    'memory.portrait.empty.body': '随着对话和来源逐渐积累，Magi 会在这里整理出你的长期项目、偏好与协作方式。',
    'memory.portrait.empty.helper': '只有反复出现、较可信的线索，才会成为这里的长期理解。',
    'memory.portrait.empty.actions.chat': '开始对话',
    'memory.portrait.empty.actions.sources': '连接来源',
    'memory.portrait.recent.title': '最近的你',
    'memory.portrait.recent.meta': '最近的线索，不会直接当成长期人格',
    'memory.portrait.recent.kinds.active_work': '最近在推进：{{value}}',
    'memory.portrait.recent.kinds.preference_interest': '最近在关注：{{value}}',
    'memory.portrait.identity.title': '你是谁',
    'memory.portrait.identity.fields.preferredFormOfAddress': '称呼',
    'memory.portrait.identity.fields.realName': '真实姓名',
    'memory.portrait.identity.fields.birthDate': '生日',
    'memory.portrait.identity.fields.homeLocation': '常住地',
    'memory.portrait.identity.fields.disallowedFormsOfAddress': '不希望使用的称呼',
    'memory.portrait.identity.empty': '未填写',
    'memory.portrait.identity.add': '点击补充',
    'memory.portrait.identity.editField': '修改{{field}}',
    'memory.portrait.identity.completeFields': '补充 {{fields}}',
    'memory.portrait.identity.fieldSeparator': '、',
    'memory.portrait.identity.source': '来源：{{source}}',
    'memory.portrait.identity.sources.settings_profile': '你的设置',
    'memory.portrait.identity.sources.chat': '对话记忆',
    'memory.portrait.identity.sources.derived': '派生',
    'memory.portrait.identity.sources.user_authored': '你告诉 Magi 的',
    'memory.portrait.identity.saveSuccess': '已保存',
    'memory.portrait.identity.saveFailed': '保存失败：{{message}}',
    'memory.portrait.identity.loadFailed': '个人资料加载失败',
    'memory.portrait.identity.retry': '重试',
    'memory.portrait.identity.refresh': '从记忆刷新建议',
    'memory.portrait.identity.refreshing': '查找中...',
    'memory.portrait.identity.refreshSuccess': '已生成记忆建议',
    'memory.portrait.identity.suggestionsTitle': '记忆建议',
    'memory.portrait.identity.suggestionsDesc': '这些来自已有记忆。',
    'memory.portrait.identity.suggestionsEmpty': '暂时没有新的建议。',
    'memory.portrait.identity.applySuggestion': '采纳',
    'memory.portrait.addFact.placeholder': '告诉 Magi 关于你的一件事…',
    'memory.portrait.addFact.submit': '提交',
    'memory.portrait.addFact.success': '已记下',
    'memory.portrait.addFact.failed': '提交失败：{{message}}',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        const label = labels[key] ?? opts?.defaultValue ?? key;
        return label.replace(/\{\{(\w+)\}\}/g, (_match, name) =>
          name in (opts ?? {}) ? String(opts?.[name]) : `{{${name}}}`
        );
      },
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/api/modules/memoryPortraitSelf', () => ({
  memoryPortraitSelfApi: { get: vi.fn() },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    submitAssertionFeedback: vi.fn(),
    applyCorrection: vi.fn(),
    getCorrectionContextOptions: vi.fn(),
  },
}));

vi.mock('@/api/modules/profile', () => ({
  profileApi: {
    getMe: vi.fn(),
    updateMe: vi.fn(),
    refreshMe: vi.fn(),
  },
}));

vi.mock('@/api/modules/manualEntries', () => ({
  manualEntriesApi: { create: vi.fn() },
}));

const buildProfile = () => ({
  user_id: 'user-1',
  entity_id: 'entity-1',
  display_name: '明日香',
  preferred_form_of_address: '明日香',
  real_name: '',
  birth_date: '',
  birth_year: null,
  age_years: null,
  age_as_of: '',
  home_location: '上海',
  communication: {},
  identity: {},
  preferences: {},
  state: {},
  field_sources: {
    preferred_form_of_address: { source: 'settings_profile' },
    home_location: { source: 'chat' },
  },
  field_conflicts: {},
  completeness_score: 0.5,
  refreshed_at: 0,
  created_at: 0,
  updated_at: 0,
});

const emptySelfView = () => ({
  world: { total_count: 0, groups: [] },
  review: { items: [] },
  recent: { items: [] },
});

const renderPage = () => render(
  <MemoryRouter>
    <MemoryPortraitPage />
  </MemoryRouter>
);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(profileApi.getMe).mockResolvedValue(buildProfile());
  vi.mocked(manualEntriesApi.create).mockResolvedValue({} as any);
  vi.mocked(memoryApi.getCorrectionContextOptions).mockResolvedValue({ items: [] });
});

describe('MemoryPortraitPage', () => {
  it('shows a retryable error when the first portrait load fails', async () => {
    vi.mocked(memoryPortraitSelfApi.get)
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce({
        generated_at: 0,
        self_view: emptySelfView(),
        is_cold_start: true,
        cold_start_line: null,
        cold_start_reason: 'no_understanding',
        is_stale: false,
      });

    renderPage();

    expect(await screen.findByRole('heading', {
      name: '暂时没能读取关于你的内容',
    })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByRole('heading', { name: '还在认识你' })).toBeInTheDocument();
    expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(2);
  });

  it('shows a retryable error instead of an empty state when rebuilding fails', async () => {
    vi.mocked(memoryPortraitSelfApi.get)
      .mockResolvedValueOnce({
        generated_at: 0,
        self_view: emptySelfView(),
        is_cold_start: false,
        cold_start_line: null,
        cold_start_reason: null,
        is_stale: true,
      })
      .mockResolvedValueOnce({
        generated_at: 1,
        self_view: emptySelfView(),
        is_cold_start: true,
        cold_start_line: null,
        cold_start_reason: 'no_understanding',
        is_stale: false,
      });

    renderPage();

    expect(await screen.findByRole('heading', {
      name: '暂时没能读取关于你的内容',
    })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '还在认识你' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByRole('heading', { name: '还在认识你' })).toBeInTheDocument();
  });

  it('renders an actionable cold-start state without an empty portrait shell', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: emptySelfView(),
      is_cold_start: true, cold_start_line: '还没结论', cold_start_reason: 'no_understanding',
      is_stale: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '还在认识你' })).toBeInTheDocument();
    });
    expect(screen.getByText('随着对话和来源逐渐积累，Magi 会在这里整理出你的长期项目、偏好与协作方式。')).toBeInTheDocument();
    expect(screen.getByText('只有反复出现、较可信的线索，才会成为这里的长期理解。')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '开始对话' })).toHaveAttribute('href', '/chat');
    expect(screen.getByRole('link', { name: '连接来源' })).toHaveAttribute('href', '/memory/sources');
    expect(screen.queryByText('还没结论')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-map')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-identity')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-recent-state')).not.toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
  });

  it('renders identity, world and recent sections as a single document flow', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 3,
          groups: [
            { id: 'identity', items: [] },
            {
              id: 'projects',
              items: [{ id: 'project-1', text: 'Magi 记忆系统', source: '', source_key: null, assertion_id: null, basis_count: 2, basis_refs: [] }],
            },
            { id: 'preferences', items: [] },
            {
              id: 'work_style',
              items: [
                { id: 'style-1', text: '直接深入', source: '', source_key: null, assertion_id: null, basis_count: 3, basis_refs: [] },
                { id: 'style-2', text: '先看代码再判断', source: '', source_key: null, assertion_id: 'assert-stable', basis_count: 2, basis_refs: [] },
              ],
            },
          ],
        },
        review: {
          items: [{ id: 'review-1', text: '待确认内容', source: 'conversation', source_key: 'conversation', assertion_id: 'assert-1', basis_count: 1, basis_refs: [] }],
        },
        recent: {
          items: [
            { id: 'recent-1', text: '插件导入', source: '', source_key: null, assertion_id: 'assert-2', basis_count: 5, basis_refs: [] },
            { id: 'recent-2', text: '最近对话更偏产品设计判断，同时会追问实现链路是否闭环。', source: '', source_key: null, assertion_id: null, basis_count: 4, basis_refs: [] },
          ],
        },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Magi 目前这样理解你' })).toBeInTheDocument();
    // 页面不再渲染「关于你」大标题,导航定位由侧栏承担
    expect(screen.queryByRole('heading', { name: '关于你' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-groups')).toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-branch-identity')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-projects')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-work_style')).toBeInTheDocument();
    expect(screen.getByText('Magi 记忆系统')).toBeInTheDocument();
    expect(screen.getByText('直接深入')).toBeInTheDocument();
    expect(within(screen.getByTestId('portrait-world-branch-work_style')).getByText('先看代码再判断')).toBeInTheDocument();

    // review queue 已移至「待确认」页面,本页不再渲染
    expect(screen.queryByText('待确认内容')).not.toBeInTheDocument();

    const identity = await screen.findByTestId('portrait-identity');
    expect(within(identity).getByText('你是谁')).toBeInTheDocument();
    expect(within(identity).getByText('明日香')).toBeInTheDocument();
    expect(within(identity).getByText('上海')).toBeInTheDocument();
    expect(within(identity).getByText('来源：你的设置')).toBeInTheDocument();
    expect(within(identity).getByText('来源：对话记忆')).toBeInTheDocument();
    // 主动补充输入行收敛在「你是谁」区块内
    expect(within(identity).getByTestId('portrait-add-fact')).toBeInTheDocument();
    expect(within(identity).getByPlaceholderText('告诉 Magi 关于你的一件事…')).toBeInTheDocument();

    const recent = screen.getByTestId('portrait-recent-state');
    expect(within(recent).getByText('最近的你')).toBeInTheDocument();
    expect(within(recent).getByText('插件导入')).toBeInTheDocument();

    // 单列文档流:你是谁(含主动补充) → Magi 的理解 → 最近的你
    const world = screen.getByTestId('portrait-world-map');
    const ordered = [identity, world, recent];
    for (let index = 0; index < ordered.length - 1; index += 1) {
      expect(
        ordered[index].compareDocumentPosition(ordered[index + 1]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }

    expect(screen.queryByText(/assertion|trait|family|L2/i)).not.toBeInTheDocument();
  });

  it('renders the backend grouped self view directly, hiding profile-projection duplicates', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 3,
          groups: [
            {
              id: 'identity',
              summary: '你希望 Magi 称呼你为 Asuka',
              items: [{ id: 'identity-1', text: 'Asuka', source: 'user_profile_projection', source_key: 'user_profile_projection', assertion_id: null, basis_count: 1, basis_refs: [] }],
            },
            { id: 'projects', summary: '长期推进 Magi 记忆系统', items: [] },
            { id: 'preferences', items: [] },
            { id: 'work_style', items: [] },
          ],
        },
        review: { items: [] },
        recent: {
          items: [{ id: 'recent-1', text: '正在验证 L2 页面模型', source: 'tom', source_key: 'tom', assertion_id: null, basis_count: 2, basis_refs: [] }],
        },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();

    expect(await screen.findByText('长期推进 Magi 记忆系统')).toBeInTheDocument();
    // 来自个人资料投影的条目和摘要与「你是谁」一节重复,不再显示
    expect(screen.queryByText('你希望 Magi 称呼你为 Asuka')).not.toBeInTheDocument();
    expect(screen.queryByText('Asuka')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-branch-identity')).not.toBeInTheDocument();
    expect(screen.getByText('正在验证 L2 页面模型')).toBeInTheDocument();
    expect(screen.getByText('已形成 3 条理解')).toBeInTheDocument();
  });

  it('keeps every unsummarized portrait item available for correction', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 5,
          groups: [{
            id: 'preferences',
            items: [1, 2, 3, 4, 5].map((index) => ({
              id: `preference-${index}`,
              text: `偏好 ${index}`,
              correction_value: `偏好 ${index}`,
              source: '',
              source_key: null,
              assertion_id: `assert-${index}`,
              basis_count: 1,
              basis_refs: [],
            })),
          }],
        },
        review: { items: [] },
        recent: { items: [] },
      },
      is_cold_start: false,
      cold_start_line: null,
      cold_start_reason: null,
      is_stale: false,
    });

    renderPage();

    const preferences = await screen.findByTestId('portrait-world-branch-preferences');
    fireEvent.click(within(preferences).getByText('查看并修正 1 条具体记忆'));
    fireEvent.click(within(preferences).getByRole('button', { name: '修正 偏好 5' }));
    expect(await screen.findByRole('dialog', { name: '修正这条记忆' })).toBeInTheDocument();
  });

  it('renders recent interests and projects as readable temporary signals', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 2,
          groups: [
            { id: 'identity', items: [] },
            { id: 'projects', items: [] },
            { id: 'preferences', items: [] },
            { id: 'work_style', items: [] },
          ],
        },
        review: { items: [] },
        recent: {
          items: [
            {
              id: 'recent-interest', text: 'DIIV', source: '', source_key: null,
              assertion_id: 'assert-interest', basis_count: 3, basis_refs: [],
              claim_kind: 'preference_interest',
            },
            {
              id: 'recent-project', text: 'Magi', source: '', source_key: null,
              assertion_id: 'assert-project', basis_count: 3, basis_refs: [],
              claim_kind: 'active_work',
            },
          ],
        },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();

    expect(await screen.findByText('最近在关注：DIIV')).toBeInTheDocument();
    expect(screen.getByText('最近在推进：Magi')).toBeInTheDocument();
  });

  it('does not render source text for portrait items without a user-facing source', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 1,
          groups: [
            { id: 'identity', items: [] },
            {
              id: 'preferences',
              items: [{
                id: 'preference-1',
                text: 'Codex',
                source: '',
                source_key: null,
                assertion_id: 'assert-external',
                basis_count: 4,
                basis_refs: ['assertion:assert-external', 'source:external_activity'],
              }],
            },
            { id: 'work_style', items: [] },
          ],
        },
        review: { items: [] },
        recent: { items: [] },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();

    const preferences = await screen.findByTestId('portrait-world-branch-preferences');
    expect(within(preferences).getByText('Codex')).toBeInTheDocument();
    expect(within(preferences).queryByText('external_activity')).not.toBeInTheDocument();
  });

  it('hides source labels from portrait world and recent sections', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 4,
          groups: [
            { id: 'identity', items: [] },
            { id: 'preferences', items: [] },
            {
              id: 'work_style',
              items: [{
                id: 'work-style-1',
                text: '先看代码再判断',
                source: 'Chrome 浏览器历史',
                source_key: 'chrome_history',
                assertion_id: 'assert-routine',
                basis_count: 4,
                basis_refs: ['assertion:assert-routine', 'source:chrome_history'],
              }],
            },
            { id: 'projects', items: [] },
          ],
        },
        review: { items: [] },
        recent: {
          items: [{
            id: 'recent-1',
            text: '最近在验证画像页面',
            source: 'tom',
            source_key: 'tom',
            assertion_id: null,
            basis_count: 1,
            basis_refs: ['source:tom'],
          }],
        },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();

    const world = await screen.findByTestId('portrait-world-map');
    expect(within(world).getByText('先看代码再判断')).toBeInTheDocument();
    expect(within(world).queryByText('Chrome 浏览器历史')).not.toBeInTheDocument();

    const recent = screen.getByTestId('portrait-recent-state');
    expect(within(recent).getByText('最近在验证画像页面')).toBeInTheDocument();
    expect(within(recent).queryByText('总结')).not.toBeInTheDocument();
  });

  it('lets users open an exact long-term memory from a grouped summary and correct it', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: {
          total_count: 1,
          groups: [{
            id: 'work_style',
            summary: '工作和沟通方式：先讲结论',
            items: [{
              id: 'style-1', text: '先讲结论', correction_value: '先讲结论', source: '', source_key: null,
              assertion_id: 'assert-style', basis_count: 3, basis_refs: [], updated_at: 1719301200,
            }],
          }],
        },
        review: { items: [] },
        recent: { items: [] },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();
    const branch = await screen.findByTestId('portrait-world-branch-work_style');
    expect(within(branch).getByText('工作和沟通方式：先讲结论')).toBeInTheDocument();
    fireEvent.click(within(branch).getByText('查看并修正 1 条具体记忆'));
    fireEvent.click(within(branch).getByRole('button', { name: '修正 先讲结论' }));

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    expect(within(dialog).getByText('先讲结论')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('正确内容')).toHaveValue('先讲结论');
  });

  it('submits a self-declared fact through the manual entries channel', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: emptySelfView(),
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();

    const identity = await screen.findByTestId('portrait-identity');
    const addFact = await within(identity).findByTestId('portrait-add-fact');
    const input = within(addFact).getByPlaceholderText('告诉 Magi 关于你的一件事…');
    // 输入前不渲染提交按钮,保持区块安静
    expect(within(addFact).queryByRole('button', { name: '提交' })).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: '我喜欢爵士乐' } });
    const submit = within(addFact).getByRole('button', { name: '提交' });
    fireEvent.click(submit);

    await waitFor(() => expect(manualEntriesApi.create).toHaveBeenCalledTimes(1));
    expect(manualEntriesApi.create).toHaveBeenCalledWith({
      entry_id: expect.stringMatching(/^me-/),
      body: '我喜欢爵士乐',
    });
    await waitFor(() => expect(input).toHaveValue(''));
    // 提交后触发画像刷新
    await waitFor(() => expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(2));
  });
});
