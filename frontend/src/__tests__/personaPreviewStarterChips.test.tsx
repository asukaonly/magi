import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PersonaPreviewStarterChips } from '../components/onboarding/PersonaPreviewStarterChips';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

describe('PersonaPreviewStarterChips', () => {
  it('renders four starter prompts', () => {
    render(<PersonaPreviewStarterChips onPick={() => {}} />);
    expect(screen.getByTestId('persona-preview-starter-prompts')).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });

  it('invokes onPick with the starter prompt when clicked', async () => {
    const onPick = vi.fn();
    render(<PersonaPreviewStarterChips onPick={onPick} />);
    const chips = screen.getAllByRole('button');
    await userEvent.click(chips[0]);
    expect(onPick).toHaveBeenCalledOnce();
    expect(typeof onPick.mock.calls[0][0]).toBe('string');
    expect(onPick.mock.calls[0][0].length).toBeGreaterThan(0);
  });
});
