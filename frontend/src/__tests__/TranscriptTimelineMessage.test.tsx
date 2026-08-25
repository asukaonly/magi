import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/runtime/desktop', () => ({
  openExternalUrl: vi.fn(),
}));

import { TranscriptTimelineMessage } from '@/components/chat/TranscriptTimelineMessage';
import type { ChatTimelineMessage } from '@/domain/chat/state';

describe('TranscriptTimelineMessage', () => {
  it('does not render a standalone streaming caret after markdown content', () => {
    const message: ChatTimelineMessage = {
      id: 'msg-streaming-content',
      role: 'assistant',
      kind: 'assistant',
      content: '第一段\n\n第二段',
      timestamp: 1,
      streaming: true,
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

    expect(screen.getByText('第一段')).toBeInTheDocument();
    expect(screen.getByText('第二段')).toBeInTheDocument();
    expect(container.querySelector('span.inline-block.h-4.w-1\\.5')).toBeNull();
  });

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

  it('orders user message header actions before time and name', () => {
    const message: ChatTimelineMessage = {
      id: 'msg-user-header-order',
      role: 'user',
      kind: 'user',
      content: 'hello',
      timestamp: 1,
    };

    render(
      <TranscriptTimelineMessage
        message={message}
        assistantName="Magi"
        userNameLabel="You"
        timestampLabel="16:20"
        shouldReduceMotion
        avatar={null}
        headerExtras={<button type="button">Reply</button>}
      />,
    );

    const header = screen.getByRole('button', { name: 'Reply' }).closest('div');
    expect(header).not.toBeNull();
    expect(Array.from(header!.children).map((child) => child.textContent)).toEqual([
      'Reply',
      '16:20',
      'You',
    ]);
  });

  it('renders an explicit reasoning modifier without changing the message body', () => {
    const message: ChatTimelineMessage = {
      id: 'msg-user-fast',
      role: 'user',
      kind: 'user',
      content: '杭州一日游怎么安排比较好',
      timestamp: 1,
      payload: { reasoning_preference: 'fast' },
    };

    render(
      <TranscriptTimelineMessage
        message={message}
        assistantName="Magi"
        userNameLabel="You"
        timestampLabel="16:45"
        shouldReduceMotion
        avatar={null}
      />,
    );

    expect(screen.getByText('/fast')).toHaveClass('text-primary');
    expect(screen.getByText('杭州一日游怎么安排比较好')).toBeInTheDocument();
  });
});
