import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatRoleAvatar } from '@/components/chat/ChatRoleAvatar';

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({ apiBaseUrl: 'http://localhost/api' }),
}));

describe('ChatRoleAvatar', () => {
  it('renders a text fallback when the assistant has no avatar', () => {
    render(
      <ChatRoleAvatar
        role="assistant"
        assistantName="惣流·明日香·兰格雷"
        assistantAvatar=""
      />,
    );

    expect(screen.getByText('惣')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('falls back to text when the assistant avatar image fails to load', () => {
    const { container } = render(
      <ChatRoleAvatar
        role="assistant"
        assistantName="惣流·明日香·兰格雷"
        assistantAvatar="http://localhost/static/avatars/missing.png"
      />,
    );

    const image = container.querySelector<HTMLImageElement>('img');
    if (!image) {
      throw new Error('Expected assistant avatar image before load failure');
    }
    fireEvent.error(image);

    expect(container.querySelector('img')).not.toBeInTheDocument();
    expect(screen.getByText('惣')).toBeInTheDocument();
  });
});
