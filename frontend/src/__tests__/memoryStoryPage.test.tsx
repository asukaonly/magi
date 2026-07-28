import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

import { MemoryStoryPage } from '@/pages/memory-pages/MemoryStoryPage';
import { memoryStoriesApi } from '@/api/modules/memoryStories';
import type { StoryFeedPayload, StoryItem } from '@/api/modules/memoryStories';

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
        'memory.stories.actions.readFull': '阅读完整总结',
        'memory.stories.detailRail.close': '关闭详情',
        'memory.stories.evidenceChip': '{{count}} 条证据',
        'memory.stories.heroLabel': '近期重点',
        'memory.stories.sortHint': '按重要程度和时间排序',
        'memory.stories.filters.all': '全部',
        'memory.stories.filters.label': '总结分类',
        'memory.stories.filters.periodic': '时段总结',
        'memory.stories.filters.observations': '长期观察',
        'memory.stories.filters.tasks': '任务复盘',
        'memory.stories.pagination.loadMore': '加载更早总结',
        'memory.stories.pagination.loading': '正在加载…',
        'memory.stories.pagination.end': '已经看到当前加载的全部总结',
        'memory.stories.stats.highlights': '观察复盘',
        'memory.stories.stats.periodic': '时段总结',
        'memory.stories.stats.observations': '长期观察',
        'memory.stories.stats.summaryCount': '{{count}} 条总结',
        'memory.stories.stats.periodicCount': '{{count}} 条时段总结',
        'memory.stories.stats.observationsCount': '{{count}} 条长期观察',
        'memory.stories.stats.tasksCount': '{{count}} 条任务复盘',
        'memory.stories.meta.insight': '观察',
        'memory.stories.meta.periodic': '时段记录',
        'memory.stories.sections.reflections': 'Magi 的总结',
        'memory.stories.sections.reflectionsEmpty': '还没有新的总结',
        'memory.stories.sections.feed': '更早的总结',
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
): StoryItem => {
  const story = {
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
  } as StoryItem;
  const feedGroup = story.feed_group || (
    story.summary_type !== 'insight'
      ? 'periodic'
      : story.summary_category === 'state_change'
        ? 'memory_update'
        : ['task_reflection', 'goal_refinement', 'milestone_review'].includes(story.summary_category)
          ? 'tasks'
          : ['trend_shift', 'preference_emergence', 'conflict_resolution', 'risk_escalation'].includes(story.summary_category)
            ? 'observations'
            : 'other'
  );
  const displayTimestamp = story.display_timestamp || story.period_end || story.updated_at || story.period_start || 0;
  return {
    ...story,
    feed_group: feedGroup,
    summary_feed_visible: story.summary_feed_visible ?? feedGroup !== 'memory_update',
    featured_rank: story.featured_rank ?? (
      feedGroup === 'periodic' && ['week', 'month', 'quarter', 'year'].includes(story.summary_category)
        ? 0
        : null
    ),
    display_timestamp: displayTimestamp,
    preview_text: story.preview_text || story.essence_prose || story.title || story.content,
    detail_lead_text: story.detail_lead_text || (story.title ? (story.essence_prose || story.content) : ''),
  };
};

const makeStats = (items: StoryItem[]) => ({
  highlights: items.filter((story) => story.summary_type === 'insight' && story.summary_feed_visible && story.review_state !== 'archived').length,
  periodic: items.filter((story) => story.feed_group === 'periodic' && story.summary_feed_visible && story.review_state !== 'archived').length,
  observations: items.filter((story) => story.feed_group === 'observations' && story.summary_feed_visible && story.review_state !== 'archived').length,
  tasks: items.filter((story) => story.feed_group === 'tasks' && story.summary_feed_visible && story.review_state !== 'archived').length,
});

const makePayload = (
  items: StoryItem[],
  overrides: Partial<StoryFeedPayload> = {}
): StoryFeedPayload => ({
  items,
  total: items.length,
  limit: 30,
  offset: 0,
  stats: makeStats(items),
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
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([], { limit: 20 }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('memory-stories-feed')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByText('继续使用一段时间，这里会出现它对你的观察。')).toBeInTheDocument();
  });

  it('renders summary insights and temporal items in the new summary layout', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([
      makeStory('ins-1', {
        title: 'an insight',
        content: 'trend body',
        preview_text: 'trend body',
        period_end: 1700100000,
        updated_at: 1700100000,
      }),
      makeStory('day-1', {
        summary_type: 'temporal',
        summary_category: 'day',
        content: 'day digest',
        period_start: 1700000000,
        period_end: 1700086400,
        updated_at: 1700086400,
        review_state: 'neutral',
        evidence_event_count: 0,
      }),
    ], { limit: 20 }));
    renderPage();
    const page = await screen.findByTestId('memory-stories-feed');
    expect(screen.getByTestId('memory-stories-featured')).toHaveTextContent('trend body');
    expect(page.textContent).toContain('trend body');
    expect(page.textContent).toContain('day digest');
    expect(screen.getAllByText('trend body')).toHaveLength(1);
    expect(screen.queryByTestId('memory-stories-section-periodic')).not.toBeInTheDocument();
  });

  it('keeps the featured preview concise and opens full markdown in detail', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([
        makeStory('week-md', {
          summary_type: 'temporal',
          summary_category: 'week',
          content: '## 要点\n本周 **magi** 工作推进。\n\n- 修复 CI\n- 梳理人格逻辑',
          preview_text: '本周主要推进 Magi，并完成两项关键整理。',
          period_end: 1700300000,
          updated_at: 1700300000,
          evidence_event_count: 4,
        }),
    ]));

    renderPage();

    const featured = await screen.findByTestId('memory-stories-featured');
    expect(featured).toHaveTextContent('本周主要推进 Magi，并完成两项关键整理。');
    expect(featured).not.toHaveTextContent('修复 CI');
    expect(featured.querySelector('h2')).toBeNull();
    expect(featured.querySelector('li')).toBeNull();

    await userEvent.click(within(featured).getByRole('button', { name: '阅读完整总结' }));
    const detail = await screen.findByTestId('story-detail-rail');
    const detailScroll = within(detail).getByTestId('story-detail-scroll');
    expect(detailScroll.querySelector('h2')).toHaveTextContent('要点');
    expect(detailScroll.querySelector('strong')).toHaveTextContent('magi');
    expect(detailScroll.querySelectorAll('li')).toHaveLength(2);
  });

  it('uses essence prose on cards while keeping full content in detail', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([
      makeStory('week-essence', {
        summary_type: 'temporal',
        summary_category: 'week',
        content: '## 要点\n本周完整总结保留时间线和未闭合事项。\n\n## 时间线\n- 调整 L3 生成\n- 验证总结页展示',
        period_end: 1700400000,
        updated_at: 1700400000,
        evidence_event_count: 7,
        essence_prose: '本周主要调整 L3 总结，让首页更好读。',
      }),
    ]));

    renderPage();

    const featured = await screen.findByTestId('memory-stories-featured');
    expect(featured).toHaveTextContent('本周主要调整 L3 总结，让首页更好读。');
    expect(featured).not.toHaveTextContent('未闭合事项');

    await userEvent.click(within(featured).getByText('本周主要调整 L3 总结，让首页更好读。'));

    const detail = await screen.findByTestId('story-detail-rail');
    expect(detail).toHaveTextContent('本周完整总结保留时间线和未闭合事项。');
    expect(detail).toHaveTextContent('调整 L3 生成');
  });

  it('keeps the filter bar simple and filters visible summaries', async () => {
    const trendStory = makeStory('trend-1', {
      summary_category: 'trend_shift',
      content: '长期观察内容',
      period_end: 1700300000,
      updated_at: 1700300000,
    });
    const dayStory = makeStory('day-1', {
      summary_type: 'temporal',
      summary_category: 'day',
      content: '时段总结内容',
      period_end: 1700200000,
      updated_at: 1700200000,
    });
    const taskStory = makeStory('task-1', {
      summary_category: 'task_reflection',
      content: '任务复盘内容',
      period_end: 1700100000,
      updated_at: 1700100000,
    });
    vi.mocked(memoryStoriesApi.list)
      .mockResolvedValueOnce(makePayload([trendStory, dayStory, taskStory]))
      .mockResolvedValueOnce(makePayload([dayStory]))
      .mockResolvedValueOnce(makePayload([taskStory]));

    renderPage();
    const user = userEvent.setup();

    expect(await screen.findByRole('button', { name: '全部' })).toBeInTheDocument();
    expect(screen.getByTestId('memory-stories-stats')).toHaveTextContent('1 条时段总结');
    expect(screen.getByTestId('memory-stories-stats')).toHaveTextContent('1 条长期观察');
    expect(screen.getByTestId('memory-stories-stats')).toHaveTextContent('1 条任务复盘');
    expect(screen.getByTestId('memory-stories-stats')).not.toHaveTextContent('观察复盘');
    expect(screen.getByRole('button', { name: '时段总结' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '长期观察' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '任务复盘' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '近期' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '只看未归档' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '时段总结' }));
    await waitFor(() => {
      expect(memoryStoriesApi.list).toHaveBeenLastCalledWith({
        limit: 30,
        offset: 0,
        surface: 'summary',
        group: 'periodic',
      });
    });
    expect(screen.getByTestId('memory-stories-feed').textContent).toContain('时段总结内容');
    expect(screen.getByTestId('memory-stories-feed').textContent).not.toContain('长期观察内容');

    await user.click(screen.getByRole('button', { name: '任务复盘' }));
    await waitFor(() => {
      expect(memoryStoriesApi.list).toHaveBeenLastCalledWith({
        limit: 30,
        offset: 0,
        surface: 'summary',
        group: 'tasks',
      });
    });
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
      content: '一条更早的总结',
      period_end: 1700000000,
      updated_at: 1700000000,
    });

    vi.mocked(memoryStoriesApi.list)
      .mockResolvedValueOnce(makePayload(firstPage, { total: 31, limit: 30, offset: 0 }))
      .mockResolvedValueOnce(makePayload([earlierStory], { total: 31, limit: 30, offset: 30 }));

    renderPage();
    const user = userEvent.setup();

    const loadMore = await screen.findByRole('button', { name: '加载更早总结' });
    await user.click(loadMore);

    expect(memoryStoriesApi.list).toHaveBeenNthCalledWith(1, {
      limit: 30,
      offset: 0,
      surface: 'summary',
      group: undefined,
    });
    expect(memoryStoriesApi.list).toHaveBeenNthCalledWith(2, {
      limit: 30,
      offset: 30,
      surface: 'summary',
      group: undefined,
    });
    expect(await screen.findByText('一条更早的总结')).toBeInTheDocument();
    expect(screen.getByText('已经看到当前加载的全部总结')).toBeInTheDocument();
  });

  it('keeps state-change memory updates out of the summaries page', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([
      makeStory('state-1', {
        summary_category: 'state_change',
        title: '待确认记忆',
        content: 'Magi 觉得这条记忆需要确认',
        period_end: 1700100000,
        updated_at: 1700100000,
      }),
      makeStory('trend-1', {
        summary_category: 'trend_shift',
        content: '最近持续关注：Codex、DeepSeek。',
        period_end: 1700200000,
        updated_at: 1700200000,
        evidence_event_count: 6,
      }),
    ], { limit: 20 }));
    renderPage();
    const feed = await screen.findByTestId('memory-stories-feed');
    expect(feed.textContent).toContain('最近持续关注：Codex、DeepSeek。');
    expect(feed.textContent).not.toContain('待确认记忆');
    expect(feed.textContent).not.toContain('Magi 觉得这条记忆需要确认');
  });

  it('renders story cards from the feed', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([
      makeStory('s1', {
        title: '你最近的播放变得更安静了',
        content: 'trend body',
        period_start: 1700000000,
        period_end: 1700100000,
        updated_at: 1700100000,
        insight_key: 'k',
        evidence_event_count: 5,
      }),
      makeStory('s2', {
        title: '你也开始更常在午后阅读',
        content: '阅读节奏更稳定了',
        period_start: 1699900000,
        period_end: 1700000000,
        updated_at: 1700000000,
        insight_key: 'k2',
        evidence_event_count: 3,
      }),
    ], { limit: 20 }));
    renderPage();
    expect(await screen.findAllByText('你最近的播放变得更安静了')).not.toHaveLength(0);
    expect(screen.queryByTestId('story-card-s1')).not.toBeInTheDocument();
    expect(screen.getByTestId('story-card-s2')).toBeInTheDocument();
    expect(screen.getByTestId('story-card-s2').textContent).not.toContain('待确认');
    expect(screen.getByTestId('story-card-s2').textContent).toContain('3 条证据');
    expect(screen.getByTestId('story-card-s2').textContent).not.toContain('Magi 自动生成');
  });

  it('renders only an archive action on each card', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(makePayload([
      makeStory('ins-1', {
        content: 'trend body',
        period_end: 1700100000,
        updated_at: 1700100000,
      }),
      makeStory('day-1', {
        summary_type: 'temporal',
        summary_category: 'day',
        content: 'day digest',
        period_end: 1700200000,
        updated_at: 1700200000,
        review_state: 'neutral',
        evidence_event_count: 0,
      }),
    ], { limit: 20 }));
    renderPage();
    await waitFor(() => screen.getByText('trend body'));
    // No confirm/reject/note buttons anywhere
    expect(screen.queryByLabelText(/确认|Confirm/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/拒绝|Reject/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/备注|Add note/i)).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/收起|Archive/i).length).toBeGreaterThanOrEqual(1);
  });
});
