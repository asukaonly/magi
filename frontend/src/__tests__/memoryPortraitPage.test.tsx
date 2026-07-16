import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { MemoryPortraitPage } from '@/pages/memory-pages/MemoryPortraitPage';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import { memoryApi } from '@/api/modules/memory';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.portrait.title': '画像',
    'memory.portrait.subtitle': 'Magi 眼中的你',
    'memory.portrait.loading': '正在读取关于你的内容…',
    'memory.portrait.loadFailed.title': '暂时没能读取关于你的内容',
    'memory.portrait.loadFailed.body': '已有内容没有丢失，请稍后再试。',
    'memory.portrait.loadFailed.retry': '重新读取',
    'memory.portrait.segments.identity': '身份',
    'memory.portrait.segments.state': '当下',
    'memory.portrait.segments.preferences': '偏好',
    'memory.portrait.segments.relationships': '关系',
    'memory.portrait.segments.impression': '总体印象',
    'memory.portrait.world.title': '关于你',
    'memory.portrait.world.summaryTitle': 'Magi 目前这样理解你',
    'memory.portrait.world.meta': '已形成 {{count}} 条理解',
    'memory.portrait.world.inspectItems': '查看并修正 {{count}} 条具体记忆',
    'memory.portrait.world.correct': '修正',
    'memory.portrait.world.correctItem': '修正 {{value}}',
    'memory.portrait.world.editProfile': '修改个人资料',
    'memory.portrait.world.groups.identity': '身份信息',
    'memory.portrait.world.groups.projects': '长期项目',
    'memory.portrait.world.groups.preferences': '偏好与关注',
    'memory.portrait.world.groups.work_style': '协作方式',
    'memory.portrait.empty.title': '还在认识你',
    'memory.portrait.empty.body': '随着对话和来源逐渐积累，Magi 会在这里整理出你的长期项目、偏好与协作方式。',
    'memory.portrait.empty.helper': '只有反复出现、较可信的线索，才会成为这里的长期理解。',
    'memory.portrait.empty.actions.chat': '开始对话',
    'memory.portrait.empty.actions.sources': '连接来源',
    'memory.portrait.review.title': '需要你看一眼',
    'memory.portrait.review.count': '{{count}} 条',
    'memory.portrait.review.source': '来源：{{source}}',
    'memory.portrait.review.actions.confirm': '确认',
    'memory.portrait.review.actions.reject': '不准确',
    'memory.portrait.review.actions.edit': '修改',
    'memory.portrait.review.actions.save': '保存',
    'memory.portrait.review.actions.cancel': '取消',
    'memory.portrait.review.editLabel': '改成',
    'memory.portrait.recent.title': '最近的你',
    'memory.portrait.recent.meta': '最近的线索，不会直接当成长期人格',
    'memory.portrait.recent.kinds.active_work': '最近在推进：{{value}}',
    'memory.portrait.recent.kinds.preference_interest': '最近在关注：{{value}}',
    'memory.portrait.source.default': '记忆线索',
    'memory.portrait.sources.conversation': '对话',
    'memory.portrait.sources.chrome_history': 'Chrome 浏览器历史',
    'memory.portrait.sources.photo_library_apple_photos': '照片库',
    'memory.portrait.sources.user_profile_projection': '个人资料',
    'memory.portrait.sources.tom': '总结',
    'memory.stories.actions.confirm': '确认',
    'memory.stories.actions.reject': '拒绝',
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
    correctAssertion: vi.fn(),
    applyCorrection: vi.fn(),
  },
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryPortraitPage />
  </MemoryRouter>
);

beforeEach(() => vi.clearAllMocks());

describe('MemoryPortraitPage', () => {
  it('shows a retryable error when the first portrait load fails', async () => {
    vi.mocked(memoryPortraitSelfApi.get)
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce({
        generated_at: 0,
        self_view: {
          world: { total_count: 0, groups: [] },
          review: { items: [] },
          recent: { items: [] },
        },
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

  it('renders an actionable cold-start state without an empty portrait shell', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: { total_count: 0, groups: [] },
        review: { items: [] },
        recent: { items: [] },
      },
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
    expect(screen.queryByText(/已形成 .* 条理解/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-review-queue')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-recent-state')).not.toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
  });

  it('renders only meaningful portrait groups followed by review and recent sections', async () => {
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
          items: [{ id: 'review-1', text: 'Magi 记忆体验', source: 'conversation', source_key: 'conversation', assertion_id: 'assert-1', basis_count: 1, basis_refs: [] }],
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

    expect(await screen.findByRole('heading', { name: '关于你' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Magi 目前这样理解你' })).toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-groups')).toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-branch-identity')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-projects')).toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-branch-preferences')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-work_style')).toBeInTheDocument();
    expect(screen.getByText('Magi 记忆系统')).toBeInTheDocument();
    expect(screen.getByText('协作方式')).toBeInTheDocument();
    expect(screen.getByText('直接深入')).toBeInTheDocument();
    expect(screen.queryByText('稳定事实')).not.toBeInTheDocument();
    expect(screen.queryByText('Chrome')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('portrait-world-branch-work_style')).getByText('先看代码再判断')).toBeInTheDocument();

    const review = screen.getByTestId('portrait-review-queue');
    expect(within(review).getByText('需要你看一眼')).toBeInTheDocument();
    expect(within(review).getByText('Magi 记忆体验')).toBeInTheDocument();

    const recent = screen.getByTestId('portrait-recent-state');
    expect(within(recent).getByText('最近的你')).toBeInTheDocument();
    expect(within(recent).getByText('插件导入')).toBeInTheDocument();
    expect(within(recent).getByText('最近对话更偏产品设计判断，同时会追问实现链路是否闭环。')).toBeInTheDocument();

    expect(screen.queryByText('身份')).not.toBeInTheDocument();
    expect(screen.queryByText(/assertion|trait|family|L2/i)).not.toBeInTheDocument();
  });

  it('renders the backend grouped self view directly', async () => {
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
        review: {
          items: [{ id: 'review-1', text: '画像页面', source: 'conversation', source_key: 'conversation', assertion_id: 'assert-review', basis_count: 1, basis_refs: ['assertion:assert-review'] }],
        },
        recent: {
          items: [{ id: 'recent-1', text: '正在验证 L2 页面模型', source: 'tom', source_key: 'tom', assertion_id: null, basis_count: 2, basis_refs: [] }],
        },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });

    renderPage();

    expect(await screen.findByText('你希望 Magi 称呼你为 Asuka')).toBeInTheDocument();
    expect(screen.getByText('长期推进 Magi 记忆系统')).toBeInTheDocument();
    expect(screen.getByText('Asuka')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '修改个人资料' })).toBeInTheDocument();
    expect(screen.getByText('画像页面')).toBeInTheDocument();
    expect(screen.getByText('正在验证 L2 页面模型')).toBeInTheDocument();
    expect(screen.getByText('已形成 3 条理解')).toBeInTheDocument();
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
    expect(within(preferences).queryByText('记忆线索')).not.toBeInTheDocument();
    expect(within(preferences).queryByText('external_activity')).not.toBeInTheDocument();
  });

  it('hides source labels from portrait world and recent sections but keeps them in review', async () => {
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
        review: {
          items: [{
            id: 'review-1',
            text: 'Magi 记忆体验',
            source: 'conversation',
            source_key: 'conversation',
            assertion_id: 'assert-review',
            basis_count: 1,
            basis_refs: ['assertion:assert-review', 'source:conversation'],
          }],
        },
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
    expect(within(world).queryByText('照片库')).not.toBeInTheDocument();

    const recent = screen.getByTestId('portrait-recent-state');
    expect(within(recent).getByText('最近在验证画像页面')).toBeInTheDocument();
    expect(within(recent).queryByText('总结')).not.toBeInTheDocument();

    const review = screen.getByTestId('portrait-review-queue');
    expect(within(review).getByText('Magi 记忆体验')).toBeInTheDocument();
    expect(within(review).getByText('来源：对话')).toBeInTheDocument();
  });

  it('keeps confirmation quick and routes review edits through the standard correction flow', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: { total_count: 0, groups: [] },
        review: {
          items: [{ id: 'review-1', text: 'Magi 记忆体验', source: '', source_key: null, assertion_id: 'assert-1', basis_count: 1, basis_refs: [], updated_at: 1719301200 }],
        },
        recent: { items: [] },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue({} as any);
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction-1',
        request_id: 'request-1',
        actor_id: 'user:self',
        target_kind: 'assertion',
        target_id: 'assert-1',
        slot_key: 'slot-1',
        claim_fingerprint: 'claim-1',
        correction_kind: 'record_error',
        before: { trait_value: 'Magi 记忆体验' },
        replacement: { value: 'Magi 关于你页面' },
        replacement_target_id: 'assert-2',
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: { trait_value: 'Magi 关于你页面' },
      derivation_state: 'completed',
      created: true,
    });

    renderPage();

    await screen.findByText('Magi 记忆体验');
    expect(screen.queryByTestId('portrait-world-groups')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Magi 目前这样理解你' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认' }));
    expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');

    fireEvent.click(screen.getByRole('button', { name: '修改' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    fireEvent.change(within(dialog).getByLabelText('正确内容'), { target: { value: 'Magi 关于你页面' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'assertion', id: 'assert-1' },
      correction_kind: 'record_error',
      replacement: { value: 'Magi 关于你页面' },
      expected_updated_at: 1719301200,
    }));
    expect(await within(dialog).findByText('Magi 关于你页面')).toBeInTheDocument();
  });

  it('keeps a structured value intact when only its scope is corrected', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: { total_count: 0, groups: [] },
        review: {
          items: [{
            id: 'review-structured',
            text: '子涵、哈基米',
            correction_value: '["子涵", "哈基米"]',
            source: '',
            source_key: null,
            assertion_id: 'assert-structured',
            basis_count: 1,
            basis_refs: [],
            updated_at: 1719301200,
          }],
        },
        recent: { items: [] },
      },
      is_cold_start: false,
      cold_start_line: null,
      cold_start_reason: null,
      is_stale: false,
    });
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction-structured',
        request_id: 'request-structured',
        actor_id: 'user:self',
        target_kind: 'assertion',
        target_id: 'assert-structured',
        slot_key: 'slot-structured',
        claim_fingerprint: 'claim-structured',
        correction_kind: 'scope_refinement',
        before: { trait_value: '["子涵", "哈基米"]' },
        replacement: { value: '["子涵", "哈基米"]' },
        replacement_target_id: 'assert-structured-scoped',
        scope: { project: 'Magi' },
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: {
        trait_value: '["子涵", "哈基米"]',
        scope: { project: 'Magi' },
      },
      derivation_state: 'completed',
      created: true,
    });

    renderPage();

    await screen.findByText('子涵、哈基米');
    fireEvent.click(screen.getByRole('button', { name: '修改' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    expect(within(dialog).getByLabelText('正确内容')).toHaveValue('子涵、哈基米');
    fireEvent.click(within(dialog).getByRole('button', { name: /只在某些情况下是这样/ }));
    fireEvent.change(within(dialog).getByLabelText('情况类型'), { target: { value: 'project' } });
    fireEvent.change(within(dialog).getByLabelText('具体情况'), { target: { value: 'Magi' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修正' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
      target: { kind: 'assertion', id: 'assert-structured' },
      correction_kind: 'scope_refinement',
      replacement: { value: '["子涵", "哈基米"]' },
      scope: { project: 'Magi' },
      expected_updated_at: 1719301200,
    }));
  });

  it('keeps the portrait and success message visible when the post-save refresh fails', async () => {
    vi.mocked(memoryPortraitSelfApi.get)
      .mockResolvedValueOnce({
        generated_at: 0,
        self_view: {
          world: { total_count: 0, groups: [] },
          review: {
            items: [{
              id: 'review-1',
              text: 'Magi 记忆体验',
              source: '',
              source_key: null,
              assertion_id: 'assert-1',
              basis_count: 1,
              basis_refs: [],
              updated_at: 1719301200,
            }],
          },
          recent: { items: [] },
        },
        is_cold_start: false,
        cold_start_line: null,
        cold_start_reason: null,
        is_stale: false,
      })
      .mockRejectedValueOnce(new Error('portrait refresh failed'));
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction-refresh-failure',
        request_id: 'request-refresh-failure',
        actor_id: 'user:self',
        target_kind: 'assertion',
        target_id: 'assert-1',
        slot_key: 'slot-1',
        claim_fingerprint: 'claim-1',
        correction_kind: 'record_error',
        before: { trait_value: 'Magi 记忆体验' },
        replacement: { value: 'Magi 关于你页面' },
        replacement_target_id: 'assert-2',
        created_at: 1719301300,
        state: 'active',
      },
      current_claim: { trait_value: 'Magi 关于你页面' },
      derivation_state: 'completed',
      created: true,
    });

    renderPage();
    await screen.findByText('Magi 记忆体验');
    fireEvent.click(screen.getByRole('button', { name: '修改' }));
    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    fireEvent.change(within(dialog).getByLabelText('正确内容'), {
      target: { value: 'Magi 关于你页面' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: '保存修正' }));

    expect(await within(dialog).findByText('已经按你的意思修正')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-review-queue')).toBeInTheDocument();
    expect(screen.getByText('Magi 记忆体验')).toBeInTheDocument();
    expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(2);
  });

  it('asks for confirmation before removing an inaccurate review item', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: { total_count: 0, groups: [] },
        review: {
          items: [{
            id: 'review-1', text: '我每天跑步', source: '', source_key: null,
            assertion_id: 'assert-1', basis_count: 1, basis_refs: [], updated_at: 1719301200,
          }],
        },
        recent: { items: [] },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction-remove', request_id: 'request-remove', actor_id: 'user:self',
        target_kind: 'assertion', target_id: 'assert-1', slot_key: 'slot-1', claim_fingerprint: 'claim-1',
        correction_kind: 'record_error', before: { trait_value: '我每天跑步' }, created_at: 1719301300, state: 'active',
      },
      current_claim: null,
      derivation_state: 'completed',
      created: true,
    });

    renderPage();
    await screen.findByText('我每天跑步');
    fireEvent.click(screen.getByRole('button', { name: '不准确' }));

    const dialog = await screen.findByRole('dialog', { name: '修正这条记忆' });
    expect(within(dialog).getByRole('button', { name: /这条记忆不存在/ })).toHaveAttribute('aria-pressed', 'true');
    expect(memoryApi.applyCorrection).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: '确认不再使用' }));

    await waitFor(() => expect(memoryApi.applyCorrection).toHaveBeenCalledTimes(1));
    expect(vi.mocked(memoryApi.applyCorrection).mock.calls[0][0]).not.toHaveProperty('replacement');
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
              id: 'style-1', text: '先讲结论', source: '', source_key: null,
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

  it('reloads the backend portrait after confirming a review item', async () => {
    vi.mocked(memoryPortraitSelfApi.get)
      .mockResolvedValueOnce({
        generated_at: 0,
        self_view: {
          world: { total_count: 0, groups: [] },
          review: {
            items: [{
              id: 'review-1',
              text: 'Magi 记忆体验',
              source: 'conversation',
              source_key: 'conversation',
              assertion_id: 'assert-1',
              basis_count: 1,
              basis_refs: ['assertion:assert-1'],
            }],
          },
          recent: { items: [] },
        },
        is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
      })
      .mockResolvedValueOnce({
        generated_at: 1,
        self_view: {
          world: {
            total_count: 1,
            groups: [
              { id: 'identity', items: [] },
              { id: 'projects', items: [{ id: 'project-1', text: 'Magi 记忆体验', source: '', source_key: null, assertion_id: 'assert-1', basis_count: 1, basis_refs: [] }] },
            ],
          },
          review: { items: [] },
          recent: { items: [] },
        },
        is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
      });
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue({} as any);

    renderPage();

    await screen.findByText('Magi 记忆体验');
    fireEvent.click(screen.getByRole('button', { name: '确认' }));

    await waitFor(() => {
      expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(2);
    });
    expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');
    expect(screen.queryByTestId('portrait-review-queue')).not.toBeInTheDocument();
  });
});
