import { fireEvent, render, screen } from '@testing-library/react';
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
        'chat.reasoning.clearOverride': 'Clear the reasoning override for this message',
      };
      if (key === 'chat.reasoning.controlTitle') {
        return `This message: ${options?.mode}`;
      }
      if (key === 'chat.reasoning.turnOverride') {
        return `This turn · ${options?.mode}`;
      }
      return labels[key] ?? key;
    },
  }),
}));

describe('ComposerReasoningControl', () => {
  it('presents fast mode as a clearable one-turn override', () => {
    const onChange = vi.fn();

    render(
      <ComposerReasoningControl
        value="fast"
        onChange={onChange}
      />,
    );

    expect(screen.getByText('This turn · Fast')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Choose how to handle this message' }),
    ).toHaveAttribute('title', 'This message: Fast');

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Clear the reasoning override for this message',
      }),
    );
    expect(onChange).toHaveBeenCalledWith('auto');
  });

  it('does not show an override affordance in auto mode', () => {
    render(
      <ComposerReasoningControl
        value="auto"
        onChange={() => undefined}
      />,
    );

    expect(screen.queryByText(/This turn/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', {
        name: 'Clear the reasoning override for this message',
      }),
    ).not.toBeInTheDocument();
  });
});
