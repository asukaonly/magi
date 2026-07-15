import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import { memoryStoriesApi } from '@/api/modules/memoryStories';
import type { StoryItem } from '@/api/modules/memoryStories';

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: {
    evidence: vi.fn(),
  },
}));

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.stories.categories.state_change': '状态变化',
    'memory.stories.categories.week': '本周总结',
    'memory.stories.detailRail.evidenceTitle': '证据',
    'memory.stories.detailRail.evidenceToggle': '查看依据 · {{count}} 条',
    'memory.stories.detailRail.notePlaceholder': '想加个备注吗？',
    'memory.stories.detailRail.savedNote': '备注已保存',
    'memory.stories.detailRail.evidenceLoading': '加载中…',
    'memory.stories.detailRail.evidenceEmpty': '没有找到关联的事件。',
    'memory.stories.detailRail.close': '关闭详情',
    'memory.stories.actions.addNote': '备注',
    'memory.stories.evidenceChip': '{{count}} 条证据',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        const tpl = labels[key] ?? key;
        if (opts && 'count' in opts) return tpl.replace('{{count}}', String(opts.count));
        return tpl;
      },
      i18n: { language: 'zh-CN' },
    }),
  };
});

const PERIOD_START = Date.UTC(2023, 10, 15, 12) / 1000;
const PERIOD_END = Date.UTC(2023, 10, 16, 12) / 1000;

const baseStory: StoryItem = {
  summary_id: 's1',
  summary_type: 'insight',
  summary_category: 'state_change',
  title: '一段反思',
  content: '你最近开始更频繁地夜间上线',
  period_start: PERIOD_START,
  period_end: PERIOD_END,
  updated_at: PERIOD_END,
  review_state: 'pending_confirmation',
  insight_key: null,
  insight_metadata: {},
  evidence_event_count: 3,
  feed_group: 'memory_update',
  summary_feed_visible: false,
  featured_rank: null,
  display_timestamp: PERIOD_END,
  preview_text: '一段反思',
  detail_lead_text: '你最近开始更频繁地夜间上线',
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryStoriesApi.evidence).mockResolvedValue({
    summary_id: 'x', summary_type: 'insight', summary_category: 'state_change',
    mode: 'source_ids', items: [], total: 0,
  });
});

describe('StoryDetailRail', () => {
  it('renders nothing when story is null', () => {
    const { container } = render(
      <StoryDetailRail story={null} onClose={() => {}} />
    );
    expect(container.querySelector('aside')).toBeNull();
  });

  it('renders the story content and category', () => {
    render(
      <StoryDetailRail story={baseStory} onClose={() => {}} />
    );
    expect(screen.getByText('你最近开始更频繁地夜间上线')).toBeInTheDocument();
    expect(screen.getByText('状态变化 · 11/15 - 11/16', { selector: 'p' })).toBeInTheDocument();
  });

  it('does not render the note input', async () => {
    render(<StoryDetailRail story={baseStory} onClose={() => {}} />);
    await screen.findByRole('button', { name: '查看依据 · 3 条' });
    expect(screen.queryByPlaceholderText(/想加个备注/)).not.toBeInTheDocument();
  });

  it('loads and renders evidence items after expanding the evidence section', async () => {
    vi.mocked(memoryStoriesApi.evidence).mockResolvedValue({
      summary_id: 's1', summary_type: 'insight', summary_category: 'state_change',
      mode: 'source_ids',
      items: [
        { event_id: 'e1', timestamp: 1700000000, source: 'chat', event_type: 'user_message', memory_domain: 'user_authored', content: '我昨晚睡得不好' },
        { event_id: 'e2', timestamp: 1700001000, source: 'chat', event_type: 'user_message', memory_domain: 'user_authored', content: '蚊子一直在叫' },
      ],
      total: 2,
    });
    render(
      <StoryDetailRail story={baseStory} onClose={() => {}} />
    );
    expect(memoryStoriesApi.evidence).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '查看依据 · 3 条' }));
    expect(await screen.findByText('我昨晚睡得不好')).toBeInTheDocument();
    expect(screen.getByText('蚊子一直在叫')).toBeInTheDocument();
    expect(memoryStoriesApi.evidence).toHaveBeenCalledWith('s1', { limit: 25 });
  });

  it('renders the empty hint when no evidence comes back', async () => {
    vi.mocked(memoryStoriesApi.evidence).mockResolvedValue({
      summary_id: 's1', summary_type: 'temporal', summary_category: 'day',
      mode: 'time_window', items: [], total: 0,
    });
    render(
      <StoryDetailRail story={baseStory} onClose={() => {}} />
    );
    await userEvent.click(screen.getByRole('button', { name: '查看依据 · 3 条' }));
    expect(await screen.findByText('没有找到关联的事件。')).toBeInTheDocument();
  });

  it('shows the period range and keeps the generated title out of the visible header', () => {
    const storyWithGeneratedTitle: StoryItem = {
      ...baseStory,
      summary_category: 'week',
      title: '## 要点 - 这是一整段很长的本周总结，会把弹窗标题区域撑得非常高。## 时间线 - 06-30：关注国内大模型动态。## 决策与行动 - 继续追踪项目进展。',
      preview_text: '本周工作主要集中在代码审查、CI 修复和模型动态追踪。',
      content: [
        '## 要点',
        '本周工作主要集中在代码审查、CI 修复和模型动态追踪。',
        '',
        '## 时间线',
        '- 06-30：关注国内大模型动态。',
        '- 07-01：处理项目 CI 通知。',
      ].join('\n'),
      period_start: PERIOD_START,
      period_end: PERIOD_END,
      display_timestamp: PERIOD_END,
    };

    render(<StoryDetailRail story={storyWithGeneratedTitle} onClose={() => {}} />);

    expect(screen.getByText('本周总结 · 11/15 - 11/16', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '本周总结 · 11/15 - 11/16' })).toHaveClass('sr-only');
    expect(screen.queryByRole('heading', { name: '本周工作主要集中在代码审查、CI 修复和模型动态追踪。' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /## 要点/ })).not.toBeInTheDocument();
    expect(memoryStoriesApi.evidence).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '查看依据 · 3 条' })).toBeInTheDocument();
    expect(screen.getByTestId('story-detail-rail')).toHaveClass('fixed', 'flex', 'flex-col', 'overflow-hidden');
    expect(screen.getByTestId('story-detail-rail')).not.toHaveClass('relative');
    expect(screen.getByTestId('story-detail-scroll')).toHaveClass('min-h-0', 'flex-1', 'overflow-y-auto');
    expect(screen.getByTestId('story-detail-meta')).toHaveClass('w-fit');
    expect(screen.getByTestId('story-detail-header')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '关闭详情' })).toBeInTheDocument();
  });
});
