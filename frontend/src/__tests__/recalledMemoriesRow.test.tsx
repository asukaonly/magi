import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RecalledMemoriesRow } from '@/components/chat/RecalledMemoriesRow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: Record<string, unknown>) => {
      const template = String(options?.defaultValue ?? _key);
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? ''));
    },
    i18n: { language: 'zh-CN' },
  }),
}));

const memory = {
  kind: 'event',
  sourceLayer: 'L1',
  statement: 'Visited example.com',
  topic: 'example.com',
};

describe('RecalledMemoriesRow', () => {
  it('keeps memory details collapsed until the summary is expanded', () => {
    render(<RecalledMemoriesRow memories={[memory]} />);

    const trigger = screen.getByRole('button', { name: '1 条记忆引用' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Visited example.com')).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Visited example.com')).toBeInTheDocument();
  });

  it('separates expandable reference count from exhaustive coverage', () => {
    render(
      <RecalledMemoriesRow
        memories={[memory]}
        summary={{
          coverageKind: 'exhaustive',
          canClaimTotal: true,
          totalCount: 12,
          domain: 'browser',
        }}
      />,
    );

    const trigger = screen.getByRole('button', { name: '1 条记忆引用' });
    expect(screen.queryByText('共找到 12 条相关记录，本次引用 1 条')).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(screen.getByText('共找到 12 条相关记录，本次引用 1 条')).toBeInTheDocument();
  });

  it('shows exhaustive coverage without an expand affordance when no references are available', () => {
    render(
      <RecalledMemoriesRow
        memories={[]}
        summary={{
          coverageKind: 'exhaustive',
          canClaimTotal: true,
          totalCount: 12,
          domain: 'browser',
        }}
      />,
    );

    expect(screen.getByText('已完整统计 12 条相关记录')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
