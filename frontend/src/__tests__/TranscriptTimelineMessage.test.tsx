import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/runtime/desktop', () => ({
  openExternalUrl: vi.fn(),
}));

import { TranscriptTimelineMessage } from '@/components/chat/TranscriptTimelineMessage';
import type { ChatTimelineMessage } from '@/domain/chat/state';

describe('TranscriptTimelineMessage', () => {
  it('preserves ordered list start numbers from markdown', () => {
    const message: ChatTimelineMessage = {
      id: 'msg-ordered-list',
      role: 'assistant',
      kind: 'assistant',
      content: '2. 第二部分\n3. 第三部分',
      timestamp: 1,
      messageKind: 'assistant_rhythm_segment',
    };

    const { container } = render(
      <TranscriptTimelineMessage
        message={message}
        assistantName="Magi"
        userNameLabel="You"
        timestampLabel="16:20"
        shouldReduceMotion
        avatar={null}
      />,
    );

    expect(screen.getByText('第二部分')).toBeInTheDocument();
    const orderedList = container.querySelector('ol');
    expect(orderedList).not.toBeNull();
    expect(orderedList).toHaveAttribute('start', '2');
  });
});