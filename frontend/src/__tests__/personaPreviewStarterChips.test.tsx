import { render, screen, within } from '@testing-library/react';
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
  it('renders four starter prompts expanded by default', () => {
    render(<PersonaPreviewStarterChips onPick={() => {}} />);
    const grid = screen.getByTestId('persona-preview-starter-prompts');
    expect(within(grid).getAllByRole('button')).toHaveLength(4);
    expect(screen.getByTestId('persona-starter-prompts-toggle')).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('invokes onPick with the starter prompt when clicked', async () => {
    const onPick = vi.fn();
    render(<PersonaPreviewStarterChips onPick={onPick} />);
    const grid = screen.getByTestId('persona-preview-starter-prompts');
    await userEvent.click(within(grid).getAllByRole('button')[0]);
    expect(onPick).toHaveBeenCalledOnce();
    expect(typeof onPick.mock.calls[0][0]).toBe('string');
    expect(onPick.mock.calls[0][0].length).toBeGreaterThan(0);
  });

  it('collapses and re-expands via the toggle', async () => {
    render(<PersonaPreviewStarterChips onPick={() => {}} />);
    const toggle = screen.getByTestId('persona-starter-prompts-toggle');

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('persona-preview-starter-prompts')).not.toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('persona-preview-starter-prompts')).toBeInTheDocument();
  });
});
