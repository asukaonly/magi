import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ComposerReasoningControl } from '@/components/chat/ComposerReasoningControl';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { mode?: string }) => {
      const labels: Record<string, string> = {
        'chat.reasoning.auto.label': 'Auto',
        'chat.reasoning.fast.label': 'Fast',
        'chat.reasoning.deep.label': 'Deep',
        'chat.reasoning.controlLabel': 'Choose how to handle this message',
      };
      if (key === 'chat.reasoning.controlTitle') {
        return `This message: ${options?.mode}`;
      }
      return labels[key] ?? key;
    },
  }),
}));

describe('ComposerReasoningControl', () => {
  it('keeps the toolbar affordance visually stable for an inline modifier', () => {
    render(
      <ComposerReasoningControl
        value="fast"
        onChange={() => undefined}
      />,
    );

    expect(
      screen.getByRole('button', { name: 'Choose how to handle this message' }),
    ).toHaveAttribute('title', 'This message: Fast');
    expect(screen.queryByText('Fast')).not.toBeInTheDocument();
  });

  it('lets the user choose a modifier from the unchanged icon control', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ComposerReasoningControl
        value="auto"
        onChange={onChange}
      />,
    );

    await user.click(
      screen.getByRole('button', { name: 'Choose how to handle this message' }),
    );
    await user.click(screen.getByText('Fast'));
    expect(onChange).toHaveBeenCalledWith('fast');
  });
});
