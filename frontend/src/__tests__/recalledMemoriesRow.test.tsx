import { render, screen } from '@testing-library/react';
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
  it('shows exhaustive structured coverage instead of only recalled sample count', () => {
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

    expect(screen.getByText('已完整统计 12 条相关记录')).toBeInTheDocument();
    expect(screen.queryByText('展示 1 条记忆引用')).not.toBeInTheDocument();
  });

  it('keeps the existing sample summary when coverage is not exhaustive', () => {
    render(<RecalledMemoriesRow memories={[memory]} />);

    expect(screen.getByText('展示 1 条记忆引用')).toBeInTheDocument();
  });
});
