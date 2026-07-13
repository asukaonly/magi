import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ContextUsageRing } from '@/components/chat/ContextUsageRing';
import { useContextUsageStore } from '@/stores/context-usage';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: Record<string, unknown>) => {
      const template = String(options?.defaultValue ?? _key);
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? ''));
    },
  }),
}));

vi.mock('@/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: ReactNode }) => children,
  Tooltip: ({ children }: { children: ReactNode }) => children,
  TooltipTrigger: ({ children }: { children: ReactNode }) => children,
  TooltipContent: ({ children }: { children: ReactNode }) => <div role="tooltip">{children}</div>,
}));

describe('ContextUsageRing', () => {
  beforeEach(() => {
    useContextUsageStore.getState().reset();
  });

  it('shows compact used and total context amounts in its tooltip', () => {
    useContextUsageStore.getState().update('session-1', {
      used_tokens: 10_000,
      window_size: 256_000,
      threshold: 192_000,
    });

    render(<ContextUsageRing sessionId="session-1" />);

    const meter = screen.getByRole('meter', {
      name: '上下文用量：10k / 256k（4%）',
    });
    expect(meter).not.toHaveAttribute('title');
    expect(meter).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tooltip')).toHaveTextContent('10k / 256k');
  });

  it('explains that the total is unavailable before usage arrives', () => {
    render(<ContextUsageRing sessionId="session-1" />);

    expect(screen.getByRole('status', { name: '上下文用量：0 / —' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tooltip')).toHaveTextContent('0 / —');
  });
});
