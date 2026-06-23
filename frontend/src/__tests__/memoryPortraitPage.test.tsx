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
    'memory.portrait.world.rootMeta': '从记忆里连接出来的身份、偏好、习惯、足迹和互动方式',
    'memory.portrait.world.groups.identity': '身份信息',
    'memory.portrait.world.groups.preferences': '偏好与关注',
    'memory.portrait.world.groups.routine': '习惯与工具',
    'memory.portrait.world.groups.places': '足迹与场景',
    'memory.portrait.world.groups.communication': '互动方式',
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
      t: (key: string, opts?: { defaultValue?: string }) => labels[key] ?? opts?.defaultValue ?? key,
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
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [], is_cold_start: true, cold_start_line: '还没结论', cold_start_reason: 'no_observations',
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
    expect(within(root).getByText('从记忆里连接出来的身份、偏好、习惯、足迹和互动方式')).toBeInTheDocument();
    expect(screen.getByText('你的世界')).toBeInTheDocument();
    expect(screen.getByText('身份信息')).toBeInTheDocument();
    expect(screen.getByText('偏好与关注')).toBeInTheDocument();
    expect(screen.getByText('习惯与工具')).toBeInTheDocument();
    expect(screen.getByText('足迹与场景')).toBeInTheDocument();
    expect(screen.getByText('互动方式')).toBeInTheDocument();
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
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [
        { kind: 'assertion', text: '偏好：current_project = Magi 记忆系统', basis_count: 2, basis_summary: 'user_profile_projection', basis_refs: ['family:preference_profile', 'preference:current_project'] },
        { kind: 'assertion', text: '沟通风格：response_style.preferred = 直接深入', basis_count: 3, basis_summary: 'user_profile_projection', basis_refs: ['family:communication_profile', 'communication:response_style.preferred'] },
        { kind: 'relationship', text: '常用工具：Chrome', basis_count: 4, basis_summary: 'browser history', basis_refs: ['source:chrome-history'] },
        { kind: 'assertion', text: 'project_tool: 项目管理工具', basis_count: 2, basis_summary: 'L2 assertion', basis_refs: ['assertion:assert-stable', 'family:routine_profile', 'status:stable', 'source:conversation'] },
        { kind: 'assertion', text: 'focus_project: Magi 记忆体验', basis_count: 1, basis_summary: 'L2 assertion', basis_refs: ['assertion:assert-1', 'family:preference_profile', 'status:tentative', 'source:conversation'] },
        { kind: 'assertion', text: '近期状态：focus = 插件导入', basis_count: 5, basis_summary: 'L2 assertion', basis_refs: ['assertion:assert-2', 'family:state_profile', 'status:stable', 'source:conversation'] },
        { kind: 'reflection', text: '最近对话更偏产品设计判断，同时会追问实现链路是否闭环。', basis_count: 4, basis_summary: 'tom', basis_refs: ['tom-1'] },
      ],
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
    expect(within(root).getByText('从记忆里连接出来的身份、偏好、习惯、足迹和互动方式')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-identity')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-preferences')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-routine')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-places')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-branch-communication')).toBeInTheDocument();
    screen.getAllByTestId(/^portrait-world-branch-/).forEach((branch) => {
      expect(branch.className).not.toContain('border-l');
    });
    expect(screen.queryByTestId('portrait-world-trunk')).not.toBeInTheDocument();
    expect(screen.queryAllByTestId('portrait-world-trunk-segment')).toHaveLength(0);
    expect(within(screen.getByTestId('portrait-world-branch-communication')).queryByTestId('portrait-world-trunk-segment')).not.toBeInTheDocument();
    expect(screen.getByTestId('portrait-world-tree').querySelector('svg')).not.toBeInTheDocument();
    expect(screen.getByText('Magi 记忆系统')).toBeInTheDocument();
    expect(screen.getByText('互动方式')).toBeInTheDocument();
    expect(screen.getByText('直接深入')).toBeInTheDocument();
    expect(screen.getByText('习惯与工具')).toBeInTheDocument();
    expect(screen.queryByText('Chrome')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('portrait-world-branch-routine')).getByText('项目管理工具')).toBeInTheDocument();
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

  it('uses backend grouped self view instead of regrouping observations in the page', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [],
      self_view: {
        world: {
          total_count: 3,
          groups: [
            { id: 'identity', items: [{ id: 'identity-1', text: 'Asuka', source: 'user_profile_projection', source_key: 'user_profile_projection', assertion_id: null, basis_count: 1, basis_refs: [] }] },
            { id: 'preferences', items: [] },
            { id: 'routine', items: [] },
            { id: 'places', items: [] },
            { id: 'communication', items: [] },
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

    expect(await screen.findByText('Asuka')).toBeInTheDocument();
    expect(screen.getByText('画像页面')).toBeInTheDocument();
    expect(screen.getByText('正在验证 L2 页面模型')).toBeInTheDocument();
    expect(screen.getByText('基于 {{count}} 条理解')).toBeInTheDocument();
  });

  it('does not render source text for portrait items without a user-facing source', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [],
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
            { id: 'routine', items: [] },
            { id: 'places', items: [] },
            { id: 'communication', items: [] },
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

  it('routes review queue actions to assertion feedback and correction APIs', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [
        { kind: 'assertion', text: 'focus_project: Magi 记忆体验', basis_count: 1, basis_summary: 'L2 assertion', basis_refs: ['assertion:assert-1', 'family:preference_profile', 'status:tentative'] },
      ],
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
});
