import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { FirstConversationChips } from '../components/chat/FirstConversationChips';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('FirstConversationChips', () => {
  it('renders 4 chips', () => {
    render(<FirstConversationChips onPick={() => {}} />);
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });

  it('invokes onPick with the chip prompt when clicked', async () => {
    const onPick = vi.fn();
    render(<FirstConversationChips onPick={onPick} />);
    await userEvent.click(screen.getAllByRole('button')[0]);
    expect(onPick).toHaveBeenCalledOnce();
    expect(typeof onPick.mock.calls[0][0]).toBe('string');
    expect(onPick.mock.calls[0][0].length).toBeGreaterThan(0);
  });
});
