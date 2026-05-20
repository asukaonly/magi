import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryStoryPage } from '@/pages/memory-pages/MemoryStoryPage';
import { memoryStoriesApi } from '@/api/modules/memoryStories';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const labels: Record<string, string> = {
        'memory.stories.title': '故事',
        'memory.stories.subtitle': 'Magi 最近编织出的反思和阶段总结。',
        'memory.stories.emptyTitle': '还没有 Magi 关于你的反思',
        'memory.stories.emptyBody': '继续使用一段时间，这里会出现它对你的观察。',
        'memory.stories.actions.confirm': '确认',
        'memory.stories.actions.reject': '拒绝',
        'memory.stories.actions.archive': '收起',
        'memory.stories.actions.addNote': '备注',
        'memory.stories.actions.viewEvidence': '查看证据',
        'memory.stories.evidenceChip': '{{count}} 条证据',
      };
      return labels[key] ?? key;
    },
    i18n: { language: 'zh-CN' },
  }),
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: {
    list: vi.fn(),
    review: vi.fn(),
  },
}));

const renderPage = () =>
  render(
    <MemoryRouter>
      <MemoryStoryPage />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
});

describe('MemoryStoryPage', () => {
  it('shows empty state when feed has no items', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('memory-stories-empty')).toBeInTheDocument();
    });
  });

  it('renders story cards from the feed', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [{
        summary_id: 's1',
        summary_type: 'insight',
        summary_category: 'state_change',
        title: '你最近的播放变得更安静了',
        content: 'state change body',
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
    await waitFor(() => {
      expect(screen.getByText('你最近的播放变得更安静了')).toBeInTheDocument();
    });
    expect(screen.getByTestId('story-card-s1')).toBeInTheDocument();
  });

  it('confirms a story when the confirm button is clicked', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [{
        summary_id: 's1', summary_type: 'insight', summary_category: 'state_change',
        title: 't', content: 'c', period_start: 0, period_end: 1700100000,
        updated_at: 1700100000, review_state: 'pending_confirmation',
        insight_key: null, insight_metadata: {}, evidence_event_count: 1,
      }],
      total: 1, limit: 20, offset: 0,
    });
    vi.mocked(memoryStoriesApi.review).mockResolvedValue({ ok: true, summary_id: 's1', review_state: 'confirmed' });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByTestId('story-card-s1'));
    await user.click(screen.getByLabelText(/确认|Confirm/i));
    await waitFor(() => {
      expect(memoryStoriesApi.review).toHaveBeenCalledWith('s1', { review_state: 'confirmed', user_note: null });
    });
  });
});
