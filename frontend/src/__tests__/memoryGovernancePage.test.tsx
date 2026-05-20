import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { MemoryGovernancePage } from '@/pages/memory-pages/MemoryGovernancePage';
import { memoryStoriesApi } from '@/api/modules/memoryStories';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.governance.title': '治理',
    'memory.governance.subtitle': '可审阅、可纠正、可遗忘的记忆控制台。',
    'memory.governance.sections.pendingReview': '待审阅',
    'memory.governance.sections.forget': '遗忘',
    'memory.governance.sections.privacy': '隐私范围',
    'memory.governance.sections.developer': '开发者视图',
    'memory.governance.pendingReviewBody': '...',
    'memory.governance.developerBody': '...',
    'memory.governance.forgetBody': '从这里删除…',
    'memory.governance.privacyBody': '查看每个来源…',
    'memory.nav.dev.events': '原始事件 (L1)',
    'memory.nav.dev.knowledge': '结构化知识 (L2)',
    'memory.nav.dev.skills': '工具技能 (L4)',
    'memory.episodes.actions.forget': '遗忘',
    'memory.stories.actions.confirm': '确认',
    'memory.stories.actions.reject': '拒绝',
    'memory.stories.actions.archive': '收起',
    'memory.stories.actions.addNote': '备注',
    'memory.stories.actions.viewEvidence': '查看证据',
    'memory.stories.evidenceChip': '{{count}} 条证据',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        const tpl = labels[key] ?? (opts?.defaultValue as string | undefined) ?? key;
        if (typeof tpl === 'string' && opts && 'count' in opts) {
          return tpl.replace('{{count}}', String(opts.count));
        }
        return tpl;
      },
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: { list: vi.fn(), review: vi.fn() },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: { forgetEpisode: vi.fn() },
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryGovernancePage />
  </MemoryRouter>
);

beforeEach(() => vi.clearAllMocks());

describe('MemoryGovernancePage', () => {
  it('shows pending-review count from filtered story feed', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        { summary_id: 'p1', summary_type: 'insight', summary_category: 'state_change',
          title: 't', content: 'c', period_start: 0, period_end: 0, updated_at: 0,
          review_state: 'pending_confirmation', insight_key: null, insight_metadata: {}, evidence_event_count: 3 },
        { summary_id: 'p2', summary_type: 'insight', summary_category: 'state_change',
          title: 't', content: 'c', period_start: 0, period_end: 0, updated_at: 0,
          review_state: 'pending_confirmation', insight_key: null, insight_metadata: {}, evidence_event_count: 2 },
        // One non-pending item should be filtered out:
        { summary_id: 'p3', summary_type: 'insight', summary_category: 'state_change',
          title: 't', content: 'c', period_start: 0, period_end: 0, updated_at: 0,
          review_state: 'confirmed', insight_key: null, insight_metadata: {}, evidence_event_count: 1 },
      ],
      total: 3, limit: 30, offset: 0,
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId('governance-pending-count')).toHaveTextContent('2'));
  });

  it('renders developer-view links pointing to legacy layer pages', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 });
    renderPage();
    await waitFor(() => screen.getByText('原始事件 (L1)'));
    expect(screen.getByRole('link', { name: '原始事件 (L1)' })).toHaveAttribute('href', '/memory/events');
    expect(screen.getByRole('link', { name: '结构化知识 (L2)' })).toHaveAttribute('href', '/memory/knowledge');
    expect(screen.getByRole('link', { name: '工具技能 (L4)' })).toHaveAttribute('href', '/memory/skills');
  });
});
