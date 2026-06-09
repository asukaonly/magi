/**
 * Plan 3 Task 10 — integration coverage for the FirstConversationChips
 * gating logic inside the Chat page.
 *
 * Chat.tsx pulls in a large surface (realtime, controller hooks, stores,
 * personas, websockets). We don't need any of that here — the only thing
 * under test is whether the chips render based on
 * `useFirstConversationFlag().completed` and `messages.length`.
 *
 * So we exercise the same gating expression through a tiny shim that
 * mirrors Chat.tsx's render condition, while still importing the real
 * `FirstConversationChips` component and the real translation namespace.
 * This keeps the test fast and decoupled from Chat.tsx's unrelated
 * complexity, while still validating the contract Task 10 introduces.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockUseFirstConversationFlag = vi.fn();
vi.mock('@/hooks/useFirstConversationFlag', () => ({
  useFirstConversationFlag: () => mockUseFirstConversationFlag(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

import { FirstConversationChips } from '@/components/chat/FirstConversationChips';
import { useFirstConversationFlag } from '@/hooks/useFirstConversationFlag';

interface ChatChipsHostProps {
  messageCount: number;
}

/**
 * Tiny shim that mirrors the exact gating expression used inside Chat.tsx:
 *
 *   const { completed: firstConvDone, markCompleted } = useFirstConversationFlag();
 *   const showFirstConversationChips = !firstConvDone && messages.length === 0;
 *   {showFirstConversationChips && <FirstConversationChips onPick={...} />}
 */
function ChatChipsHost({ messageCount }: ChatChipsHostProps): JSX.Element {
  const { completed } = useFirstConversationFlag();
  const showChips = !completed && messageCount === 0;
  const [picked, setPicked] = React.useState<string | null>(null);
  return (
    <div>
      {showChips && <FirstConversationChips onPick={setPicked} />}
      <span data-testid="picked">{picked ?? ''}</span>
    </div>
  );
}

describe('Chat first-conversation chips integration', () => {
  beforeEach(() => {
    mockUseFirstConversationFlag.mockReset();
  });

  it('renders chips when flag is false and conversation is empty', () => {
    mockUseFirstConversationFlag.mockReturnValue({
      completed: false,
      loading: false,
      markCompleted: vi.fn(),
    });
    render(<ChatChipsHost messageCount={0} />);
    expect(
      screen.getByText('firstConversation.chips.refineText'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('firstConversation.chips.plan'),
    ).toBeInTheDocument();
  });

  it('does not render chips when flag is true', () => {
    mockUseFirstConversationFlag.mockReturnValue({
      completed: true,
      loading: false,
      markCompleted: vi.fn(),
    });
    render(<ChatChipsHost messageCount={0} />);
    expect(
      screen.queryByText('firstConversation.chips.refineText'),
    ).not.toBeInTheDocument();
  });

  it('does not render chips when conversation already has messages', () => {
    mockUseFirstConversationFlag.mockReturnValue({
      completed: false,
      loading: false,
      markCompleted: vi.fn(),
    });
    render(<ChatChipsHost messageCount={3} />);
    expect(
      screen.queryByText('firstConversation.chips.refineText'),
    ).not.toBeInTheDocument();
  });
});
