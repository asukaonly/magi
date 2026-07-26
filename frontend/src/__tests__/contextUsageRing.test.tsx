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
      name: '最近一次回答上下文：10k / 256k；压缩线占用 5%',
    });
    expect(meter).not.toHaveAttribute('title');
    expect(meter).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      '最近一次回答：10k / 256k · 压缩线 192k',
    );
  });

  it('does not present a configured limit as measured usage before a snapshot arrives', () => {
    render(
      <ContextUsageRing
        sessionId="session-1"
        configuredWindowSize={1_000_000}
      />,
    );

    const status = screen.getByRole('status', {
      name: '最近一次回答上下文：— / 1M',
    });
    expect(status).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tooltip')).toHaveTextContent('— / 1M');
  });

  it('keeps token usage paired with the model window captured for that turn', () => {
    useContextUsageStore.getState().update('session-1', {
      used_tokens: 10_000,
      window_size: 256_000,
      threshold: 192_000,
    });

    render(
      <ContextUsageRing
        sessionId="session-1"
        configuredWindowSize={1_000_000}
      />,
    );

    expect(screen.getByRole('meter', {
      name: '最近一次回答上下文：10k / 256k；压缩线占用 5%',
    })).toHaveAttribute('aria-valuemax', '192000');
    expect(screen.getByRole('tooltip')).toHaveTextContent('压缩线 192k');
  });

  it('explains that the total is unavailable before usage arrives', () => {
    render(<ContextUsageRing sessionId="session-1" />);

    expect(screen.getByRole('status', { name: '最近一次回答上下文：— / —' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tooltip')).toHaveTextContent('— / —');
  });

  it('shows a positive value below one percent instead of zero', () => {
    useContextUsageStore.getState().update('session-1', {
      used_tokens: 2_633,
      window_size: 1_000_000,
      threshold: 500_000,
    });

    render(<ContextUsageRing sessionId="session-1" />);

    expect(screen.getByRole('meter', {
      name: '最近一次回答上下文：2.6k / 1M；压缩线占用 <1%',
    })).toBeInTheDocument();
  });
});
