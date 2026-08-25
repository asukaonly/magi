import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ComposerCommandTextarea } from '@/components/chat/ComposerCommandTextarea';

describe('ComposerCommandTextarea', () => {
  it('highlights a recognized modifier without changing the editable value', () => {
    render(
      <ComposerCommandTextarea
        aria-label="message"
        value="/fast Explain HTTPS"
        onChange={() => undefined}
      />,
    );

    const textarea = screen.getByRole('textbox', { name: 'message' });
    expect(textarea).toHaveValue('/fast Explain HTTPS');
    expect(textarea).toHaveClass('text-transparent', 'caret-foreground');
    expect(screen.getByTestId('composer-command-prefix')).toHaveTextContent('/fast');
    expect(screen.getByTestId('composer-command-prefix')).toHaveClass('text-primary');
    expect(screen.getByTestId('composer-command-highlight')).toHaveTextContent(
      '/fast Explain HTTPS',
    );
  });

  it('keeps unknown slash text in the native textarea style', () => {
    render(
      <ComposerCommandTextarea
        aria-label="message"
        value="/fastest route"
        onChange={() => undefined}
      />,
    );

    expect(screen.getByRole('textbox', { name: 'message' })).not.toHaveClass(
      'text-transparent',
    );
    expect(screen.queryByTestId('composer-command-highlight')).not.toBeInTheDocument();
  });

  it('uses the native text while an IME composition is active', () => {
    const onCompositionStart = vi.fn();
    const onCompositionEnd = vi.fn();
    render(
      <ComposerCommandTextarea
        aria-label="message"
        value="/deep 比较两个方案"
        onChange={() => undefined}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={onCompositionEnd}
      />,
    );

    const textarea = screen.getByRole('textbox', { name: 'message' });
    fireEvent.compositionStart(textarea);
    expect(onCompositionStart).toHaveBeenCalledTimes(1);
    expect(textarea).not.toHaveClass('text-transparent');
    expect(screen.queryByTestId('composer-command-highlight')).not.toBeInTheDocument();

    fireEvent.compositionEnd(textarea);
    expect(onCompositionEnd).toHaveBeenCalledTimes(1);
    expect(textarea).toHaveClass('text-transparent');
    expect(screen.getByTestId('composer-command-prefix')).toHaveTextContent('/deep');
  });

  it('keeps the decoration aligned with textarea scrolling', () => {
    const { rerender } = render(
      <ComposerCommandTextarea
        aria-label="message"
        value={`/auto ${Array.from({ length: 20 }, (_, index) => `line ${index}`).join('\n')}`}
        onChange={() => undefined}
      />,
    );

    const textarea = screen.getByRole('textbox', { name: 'message' });
    Object.defineProperty(textarea, 'scrollTop', { configurable: true, value: 28 });
    fireEvent.scroll(textarea);

    expect(screen.getByTestId('composer-command-highlight').firstElementChild).toHaveStyle({
      transform: 'translateY(-28px)',
    });

    Object.defineProperty(textarea, 'scrollTop', { configurable: true, value: 0 });
    rerender(
      <ComposerCommandTextarea
        aria-label="message"
        value="/auto next message"
        onChange={() => undefined}
      />,
    );
    expect(screen.getByTestId('composer-command-highlight').firstElementChild).toHaveStyle({
      transform: 'translateY(-0px)',
    });
  });
});
