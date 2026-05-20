import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import type { StoryItem } from '@/api/modules/memoryStories';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.stories.categories.state_change': '状态变化',
    'memory.stories.detailRail.evidenceTitle': '证据',
    'memory.stories.detailRail.notePlaceholder': '想加个备注吗？',
    'memory.stories.detailRail.savedNote': '备注已保存',
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
};

describe('StoryDetailRail', () => {
  it('renders nothing when story is null', () => {
    const { container } = render(
      <StoryDetailRail story={null} onClose={() => {}} onSaveNote={() => {}} />
    );
    expect(container.querySelector('aside')).toBeNull();
  });

  it('renders the story content and category', () => {
    render(
      <StoryDetailRail story={baseStory} onClose={() => {}} onSaveNote={() => {}} />
    );
    expect(screen.getByText('你最近开始更频繁地夜间上线')).toBeInTheDocument();
    expect(screen.getByText(/状态变化/)).toBeInTheDocument();
  });

  it('saves a note when the user types and clicks save', async () => {
    const onSaveNote = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <StoryDetailRail story={baseStory} onClose={() => {}} onSaveNote={onSaveNote} />
    );
    const textarea = screen.getByPlaceholderText('想加个备注吗？');
    await user.type(textarea, '同意，最近确实如此');
    await user.click(screen.getByRole('button', { name: '备注' }));
    expect(onSaveNote).toHaveBeenCalledWith('同意，最近确实如此');
    // saved hint appears after the promise resolves
    expect(await screen.findByText('备注已保存')).toBeInTheDocument();
  });
});
