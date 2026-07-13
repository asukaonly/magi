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
    'memory.portrait.segments.identity': '身份',
    'memory.portrait.segments.state': '当下',
    'memory.portrait.segments.preferences': '偏好',
    'memory.portrait.segments.relationships': '关系',
    'memory.portrait.segments.impression': '总体印象',
    'memory.portrait.world.title': '你的世界',
    'memory.portrait.world.meta': '基于 {{count}} 条理解',
    'memory.portrait.world.empty': '还没有形成清晰的关联。',
    'memory.portrait.world.rootLabel': '你',
    'memory.portrait.world.rootTitle': 'Magi 眼中的你',
    'memory.portrait.world.rootMeta': '把目前可信的线索收拢成一个简洁轮廓',
    'memory.portrait.world.groups.identity': '身份信息',
    'memory.portrait.world.groups.projects': '长期项目',
    'memory.portrait.world.groups.preferences': '偏好与关注',
    'memory.portrait.world.groups.work_style': '协作方式',
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
    'memory.portrait.coldStartFallback': '还没结论',
    'memory.stories.actions.confirm': '确认',
    'memory.stories.actions.reject': '拒绝',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: { defaultValue?: string; value?: string }) => {
        const label = labels[key] ?? opts?.defaultValue ?? key;
        return opts?.value ? label.replace('{{value}}', opts.value) : label;
      },
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/api/modules/memoryPortraitSelf', () => ({
  memoryPortraitSelfApi: { get: vi.fn() },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: { submitAssertionFeedback: vi.fn(), correctAssertion: vi.fn() },
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryPortraitPage />
  </MemoryRouter>
);

beforeEach(() => vi.clearAllMocks());

describe('MemoryPortraitPage', () => {
  it('renders a useful cold-start shell when payload is_cold_start=true', async () => {
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
      expect(screen.getByText('还没结论')).toBeInTheDocument();
    });
    expect(screen.getByTestId('portrait-world-map')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-tree')).toBeInTheDocument();
    const root = screen.getByTestId('portrait-world-root');
    expect(root).toBeInTheDocument();
    expect(within(root).getByText('你')).toBeInTheDocument();
    expect(within(root).getByText('Magi 眼中的你')).toBeInTheDocument();
    expect(within(root).getByText('把目前可信的线索收拢成一个简洁轮廓')).toBeInTheDocument();
    expect(screen.getByText('你的世界')).toBeInTheDocument();
    expect(screen.getByText('身份信息')).toBeInTheDocument();
    expect(screen.getByText('长期项目')).toBeInTheDocument();
    expect(screen.getByText('偏好与关注')).toBeInTheDocument();
    expect(screen.getByText('协作方式')).toBeInTheDocument();
    expect(screen.queryByText('稳定事实')).not.toBeInTheDocument();
    expect(screen.queryByText('正在推进的项目')).not.toBeInTheDocument();
    expect(screen.queryByText('常用工具')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-trunk')).not.toBeInTheDocument();
    expect(screen.queryAllByTestId('portrait-world-trunk-segment')).toHaveLength(0);
    expect(screen.queryByTestId('portrait-world-root-connector')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-tree').querySelector('svg')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-review-queue')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-recent-state')).not.toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
  });

  it('renders the redesigned world, review, and recent sections without the old page header', async () => {
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

    expect(await screen.findByText('你的世界')).toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-tree')).toBeInTheDocument();
    const root = screen.getByTestId('portrait-world-root');
    expect(root).toBeInTheDocument();
    expect(within(root).getByText('你')).toBeInTheDocument();
    expect(within(root).getByText('Magi 眼中的你')).toBeInTheDocument();
    expect(within(root).getByText('把目前可信的线索收拢成一个简洁轮廓')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-identity')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-projects')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-preferences')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-work_style')).toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-branch-invariants')).not.toBeInTheDocument();
    screen.getAllByTestId(/^portrait-world-branch-/).forEach((branch) => {
      expect(branch.className).not.toContain('border-l');
    });
    expect(screen.queryByTestId('portrait-world-trunk')).not.toBeInTheDocument();
    expect(screen.queryAllByTestId('portrait-world-trunk-segment')).toHaveLength(0);
    expect(within(screen.getByTestId('portrait-world-branch-work_style')).queryByTestId('portrait-world-trunk-segment')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-tree').querySelector('svg')).not.toBeInTheDocument();
    expect(screen.getByText('Magi 记忆系统')).toBeInTheDocument();
    expect(screen.getByText('协作方式')).toBeInTheDocument();
    expect(screen.getByText('直接深入')).toBeInTheDocument();
    expect(screen.queryByText('稳定事实')).not.toBeInTheDocument();
    expect(screen.queryByText('Chrome')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('portrait-world-branch-work_style')).getByText('先看代码再判断')).toBeInTheDocument();
    expect(screen.queryByTestId('portrait-world-root-connector')).not.toBeInTheDocument();

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
    expect(screen.queryByText('Asuka')).not.toBeInTheDocument();
    expect(screen.getByText('画像页面')).toBeInTheDocument();
    expect(screen.getByText('正在验证 L2 页面模型')).toBeInTheDocument();
    expect(screen.getByText('基于 {{count}} 条理解')).toBeInTheDocument();
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
    expect(within(review).getByText('来源：{{source}}')).toBeInTheDocument();
  });

  it('routes review queue actions to assertion feedback and correction APIs', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      generated_at: 0,
      self_view: {
        world: { total_count: 0, groups: [] },
        review: {
          items: [{ id: 'review-1', text: 'Magi 记忆体验', source: '', source_key: null, assertion_id: 'assert-1', basis_count: 1, basis_refs: [] }],
        },
        recent: { items: [] },
      },
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue({} as any);
    vi.mocked(memoryApi.correctAssertion).mockResolvedValue({} as any);

    renderPage();

    await screen.findByText('Magi 记忆体验');
    fireEvent.click(screen.getByRole('button', { name: '确认' }));
    expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');

    fireEvent.click(screen.getByRole('button', { name: '修改' }));
    fireEvent.change(screen.getByLabelText('改成'), { target: { value: 'Magi 关于你页面' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(memoryApi.correctAssertion).toHaveBeenCalledWith('assert-1', 'Magi 关于你页面', 'portrait_review');
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
