import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

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
    'memory.stories.detailRail.evidenceTitle': '证据',
    'memory.stories.detailRail.notePlaceholder': '想加个备注吗？',
    'memory.stories.detailRail.savedNote': '备注已保存',
    'memory.stories.detailRail.evidenceLoading': '加载中…',
    'memory.stories.detailRail.evidenceEmpty': '没有找到关联的事件。',
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

const baseStory: StoryItem = {
  summary_id: 's1',
  summary_type: 'insight',
  summary_category: 'state_change',
  title: '一段反思',
  content: '你最近开始更频繁地夜间上线',
  period_start: 1700000000,
  period_end: 1700100000,
  updated_at: 1700100000,
  review_state: 'pending_confirmation',
  insight_key: null,
  insight_metadata: {},
  evidence_event_count: 3,
  feed_group: 'memory_update',
  summary_feed_visible: false,
  featured_rank: null,
  display_timestamp: 1700100000,
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
    expect(screen.getByText(/状态变化/)).toBeInTheDocument();
  });

  it('does not render the note input', async () => {
    render(<StoryDetailRail story={baseStory} onClose={() => {}} />);
    await screen.findByText('证据');
    expect(screen.queryByPlaceholderText(/想加个备注/)).not.toBeInTheDocument();
  });

  it('fetches and renders evidence items', async () => {
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
    expect(await screen.findByText('没有找到关联的事件。')).toBeInTheDocument();
  });

  it('keeps long markdown titles from replacing the scrollable detail body', () => {
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
    };

    render(<StoryDetailRail story={storyWithGeneratedTitle} onClose={() => {}} />);

    expect(screen.getByRole('heading', { name: '本周工作主要集中在代码审查、CI 修复和模型动态追踪。' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /## 要点/ })).not.toBeInTheDocument();
    expect(screen.getByTestId('story-detail-rail')).toHaveClass('flex', 'flex-col', 'overflow-hidden');
    expect(screen.getByTestId('story-detail-scroll')).toHaveClass('min-h-0', 'flex-1', 'overflow-y-auto');
  });
});
