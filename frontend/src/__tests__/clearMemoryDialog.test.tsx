import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ClearMemoryDialog } from '@/components/memory/ClearMemoryDialog';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options && typeof options.seconds === 'number' ? `${key}:${options.seconds}` : key,
  }),
}));

describe('ClearMemoryDialog', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('requires a short countdown before destructive confirmation becomes available', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <ClearMemoryDialog
        open
        onOpenChange={vi.fn()}
        clearing={false}
        onConfirm={onConfirm}
      />
    );

    const confirmButton = screen.getByRole('button', { name: 'memory.clearConfirm.confirmCountdown:3' });
    expect(confirmButton).toBeDisabled();

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    const enabledButton = screen.getByRole('button', { name: 'memory.clearConfirm.confirm' });
    expect(enabledButton).toBeEnabled();

    fireEvent.click(enabledButton);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
