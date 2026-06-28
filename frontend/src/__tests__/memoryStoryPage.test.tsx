import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryStoryPage } from '@/pages/memory-pages/MemoryStoryPage';
import { memoryStoriesApi } from '@/api/modules/memoryStories';
import type { StoryItem } from '@/api/modules/memoryStories';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        'memory.stories.title': '总结',
        'memory.stories.subtitle': 'Magi 整理出的阶段总结和趋势观察。',
        'memory.stories.emptyTitle': '还没有 Magi 的总结',
        'memory.stories.emptyBody': '继续使用一段时间，这里会出现它对你的观察。',
        'memory.stories.loading': '正在整理总结。',
        'memory.stories.actions.archive': '收起',
        'memory.stories.actions.viewEvidence': '查看证据',
        'memory.stories.evidenceChip': '{{count}} 条证据',
        'memory.stories.heroLabel': '近期重点',
        'memory.stories.sortHint': '按重要程度和时间排序',
        'memory.stories.filters.all': '全部',
        'memory.stories.filters.periodic': '时段总结',
        'memory.stories.filters.observations': '长期观察',
        'memory.stories.filters.tasks': '任务复盘',
        'memory.stories.pagination.loadMore': '加载更早总结',
        'memory.stories.pagination.loading': '正在加载…',
        'memory.stories.pagination.end': '已经看到当前加载的全部总结',
        'memory.stories.stats.highlights': '近期重点',
        'memory.stories.stats.periodic': '时段总结',
        'memory.stories.stats.observations': '长期观察',
        'memory.stories.meta.insight': '观察',
        'memory.stories.meta.periodic': '时段记录',
        'memory.stories.sections.reflections': 'Magi 的总结',
        'memory.stories.sections.reflectionsEmpty': '还没有新的总结',
        'memory.stories.sections.feed': '总结流',
        'memory.stories.sections.periodic': '时段记录',
        'memory.stories.sections.periodicEmpty': '还没有时段总结',
        'memory.stories.provenance': 'Magi 自动生成 · {{timestamp}}',
        'memory.stories.categories.trend_shift': '长期观察',
        'memory.stories.categories.task_reflection': '任务复盘',
        'memory.stories.categories.day': '本日总结',
        'memory.stories.categories.week': '本周总结',
      };
      let result = labels[key] ?? key;
      if (opts) {
        for (const [k, v] of Object.entries(opts)) {
          result = result.replace(`{{${k}}}`, String(v));
        }
      }
      return result;
    },
    i18n: { language: 'zh-CN' },
  }),
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: {
    list: vi.fn(),
    review: vi.fn(),
    evidence: vi.fn(),
  },
}));

const renderPage = () =>
  render(
    <MemoryRouter>
      <MemoryStoryPage />
    </MemoryRouter>
  );

const makeStory = (
  summaryId: string,
  overrides: Partial<StoryItem>
): StoryItem => ({
  summary_id: summaryId,
  summary_type: 'insight',
  summary_category: 'trend_shift',
  title: '',
  content: summaryId,
  period_start: 0,
  period_end: 1700100000,
  updated_at: 1700100000,
  review_state: 'pending_confirmation',
  insight_key: null,
  insight_metadata: {},
  evidence_event_count: 2,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryStoriesApi.evidence).mockResolvedValue({
    summary_id: 'x', summary_type: 'insight', summary_category: 'state_change',
    mode: 'source_ids', items: [], total: 0,
  });
});

describe('MemoryStoryPage', () => {
  it('shows a compact empty state without the old page header when feed has no items', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('memory-stories-feed')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByText('继续使用一段时间，这里会出现它对你的观察。')).toBeInTheDocument();
  });

  it('renders summary insights and temporal items in the new summary layout', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        {
          summary_id: 'ins-1', summary_type: 'insight', summary_category: 'trend_shift',
          title: 'an insight', content: 'trend body', period_start: 0, period_end: 1700100000,
          updated_at: 1700100000, review_state: 'pending_confirmation',
          insight_key: null, insight_metadata: {}, evidence_event_count: 2,
        } as never,
        {
          summary_id: 'day-1', summary_type: 'temporal', summary_category: 'day',
          title: '', content: 'day digest', period_start: 1700000000, period_end: 1700086400,
          updated_at: 1700086400, review_state: 'neutral',
          insight_key: null, insight_metadata: {}, evidence_event_count: 0,
        } as never,
      ],
      total: 2, limit: 20, offset: 0,
    });
    renderPage();
    const page = await screen.findByTestId('memory-stories-feed');
    expect(screen.getByTestId('memory-stories-featured')).toHaveTextContent('trend body');
    expect(page.textContent).toContain('trend body');
    expect(page.textContent).toContain('day digest');
    expect(screen.getAllByText('trend body')).toHaveLength(1);
    expect(screen.queryByTestId('memory-stories-section-periodic')).not.toBeInTheDocument();
  });

  it('renders markdown in the featured summary body', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        makeStory('week-md', {
          summary_type: 'temporal',
          summary_category: 'week',
          content: '## 要点\n本周 **magi** 工作推进。\n\n- 修复 CI\n- 梳理人格逻辑',
          period_end: 1700300000,
          updated_at: 1700300000,
          evidence_event_count: 4,
        }) as never,
      ],
      total: 1, limit: 30, offset: 0,
    });

    renderPage();

    const featured = await screen.findByTestId('memory-stories-featured');
    expect(featured.querySelector('h2')).toHaveTextContent('要点');
    expect(featured.querySelector('strong')).toHaveTextContent('magi');
    expect(featured.querySelectorAll('li')).toHaveLength(2);
    expect(featured.textContent).not.toContain('## 要点');
    expect(featured.textContent).not.toContain('**magi**');
  });

  it('keeps the filter bar simple and filters visible summaries', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        makeStory('trend-1', {
          summary_category: 'trend_shift',
          content: '长期观察内容',
          period_end: 1700300000,
          updated_at: 1700300000,
        }) as never,
        makeStory('day-1', {
          summary_type: 'temporal',
          summary_category: 'day',
          content: '时段总结内容',
          period_end: 1700200000,
          updated_at: 1700200000,
        }) as never,
        makeStory('task-1', {
          summary_category: 'task_reflection',
          content: '任务复盘内容',
          period_end: 1700100000,
          updated_at: 1700100000,
        }) as never,
      ],
      total: 3, limit: 30, offset: 0,
    });

    renderPage();
    const user = userEvent.setup();

    expect(await screen.findByRole('button', { name: '全部' })).toBeInTheDocument();
    expect(screen.getByTestId('memory-stories-stats')).toHaveTextContent('近期重点');
    expect(screen.getByTestId('memory-stories-stats')).toHaveTextContent('时段总结');
    expect(screen.getByTestId('memory-stories-stats')).toHaveTextContent('长期观察');
    expect(screen.getByRole('button', { name: '时段总结' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '长期观察' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '任务复盘' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '近期' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '只看未归档' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '时段总结' }));
    expect(screen.getByTestId('memory-stories-feed').textContent).toContain('时段总结内容');
    expect(screen.getByTestId('memory-stories-feed').textContent).not.toContain('长期观察内容');

    await user.click(screen.getByRole('button', { name: '任务复盘' }));
    expect(screen.getByTestId('memory-stories-feed').textContent).toContain('任务复盘内容');
    expect(screen.getByTestId('memory-stories-feed').textContent).not.toContain('时段总结内容');
  });

  it('loads earlier summaries from the next offset', async () => {
    const firstPage = Array.from({ length: 30 }, (_, index) => (
      makeStory(`story-${index}`, {
        content: `第 ${index + 1} 条总结`,
        period_end: 1700300000 - index,
        updated_at: 1700300000 - index,
      })
    ));
    const earlierStory = makeStory('story-30', {
      content: '更早的总结',
      period_end: 1700000000,
      updated_at: 1700000000,
    });

    vi.mocked(memoryStoriesApi.list)
      .mockResolvedValueOnce({ items: firstPage as never, total: 31, limit: 30, offset: 0 })
      .mockResolvedValueOnce({ items: [earlierStory] as never, total: 31, limit: 30, offset: 30 });

    renderPage();
    const user = userEvent.setup();

    const loadMore = await screen.findByRole('button', { name: '加载更早总结' });
    await user.click(loadMore);

    expect(memoryStoriesApi.list).toHaveBeenNthCalledWith(1, { limit: 30, offset: 0 });
    expect(memoryStoriesApi.list).toHaveBeenNthCalledWith(2, { limit: 30, offset: 30 });
    expect(await screen.findByText('更早的总结')).toBeInTheDocument();
    expect(screen.getByText('已经看到当前加载的全部总结')).toBeInTheDocument();
  });

  it('keeps state-change memory updates out of the summaries page', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        {
          summary_id: 'state-1', summary_type: 'insight', summary_category: 'state_change',
          title: '待确认记忆', content: 'Magi 觉得这条记忆需要确认', period_start: 0, period_end: 1700100000,
          updated_at: 1700100000, review_state: 'pending_confirmation',
          insight_key: null, insight_metadata: {}, evidence_event_count: 2,
        } as never,
        {
          summary_id: 'trend-1', summary_type: 'insight', summary_category: 'trend_shift',
          title: '', content: '最近持续关注：Codex、DeepSeek。', period_start: 0, period_end: 1700200000,
          updated_at: 1700200000, review_state: 'pending_confirmation',
          insight_key: null, insight_metadata: {}, evidence_event_count: 6,
        } as never,
      ],
      total: 2, limit: 20, offset: 0,
    });
    renderPage();
    const feed = await screen.findByTestId('memory-stories-feed');
    expect(feed.textContent).toContain('最近持续关注：Codex、DeepSeek。');
    expect(feed.textContent).not.toContain('待确认记忆');
    expect(feed.textContent).not.toContain('Magi 觉得这条记忆需要确认');
  });

  it('renders story cards from the feed', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [{
        summary_id: 's1',
        summary_type: 'insight',
        summary_category: 'trend_shift',
        title: '你最近的播放变得更安静了',
        content: 'trend body',
        period_start: 1700000000,
        period_end: 1700100000,
        updated_at: 1700100000,
        review_state: 'pending_confirmation',
        insight_key: 'k',
        insight_metadata: {},
        evidence_event_count: 5,
      }],
      total: 1, limit: 20, offset: 0,
    });
    renderPage();
    expect(await screen.findAllByText('你最近的播放变得更安静了')).not.toHaveLength(0);
    expect(screen.getByTestId('story-card-s1')).toBeInTheDocument();
    expect(screen.getByTestId('story-card-s1').textContent).not.toContain('待确认');
    expect(screen.getByTestId('story-card-s1').textContent).toContain('5 条证据');
    expect(screen.getByTestId('story-card-s1').textContent).not.toContain('Magi 自动生成');
  });

  it('renders only an archive action on each card', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        {
          summary_id: 'ins-1', summary_type: 'insight', summary_category: 'trend_shift',
          title: '', content: 'trend body', period_start: 0, period_end: 1700100000,
          updated_at: 1700100000, review_state: 'pending_confirmation',
          insight_key: null, insight_metadata: {}, evidence_event_count: 2,
        },
        {
          summary_id: 'day-1', summary_type: 'temporal', summary_category: 'day',
          title: '', content: 'day digest', period_start: 0, period_end: 1700200000,
          updated_at: 1700200000, review_state: 'neutral',
          insight_key: null, insight_metadata: {}, evidence_event_count: 0,
        },
      ] as never,
      total: 2, limit: 20, offset: 0,
    });
    renderPage();
    await waitFor(() => screen.getByText('trend body'));
    // No confirm/reject/note buttons anywhere
    expect(screen.queryByLabelText(/确认|Confirm/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/拒绝|Reject/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/备注|Add note/i)).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/收起|Archive/i).length).toBeGreaterThanOrEqual(1);
  });
});
