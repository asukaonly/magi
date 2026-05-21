import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { MemoryGovernancePage } from '@/pages/memory-pages/MemoryGovernancePage';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.governance.title': '治理',
    'memory.governance.subtitle': '可审阅、可纠正、可遗忘的记忆控制台。',
    'memory.governance.sections.forget': '遗忘',
    'memory.governance.sections.privacy': '隐私范围',
    'memory.governance.sections.developer': '开发者视图',
    'memory.governance.developerBody': '...',
    'memory.governance.forgetBody': '从这里删除…',
    'memory.governance.privacyBody': '查看每个来源…',
    'memory.nav.dev.events': '原始事件 (L1)',
    'memory.nav.dev.knowledge': '结构化知识 (L2)',
    'memory.nav.dev.skills': '工具技能 (L4)',
    'memory.episodes.actions.forget': '遗忘',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        const tpl = labels[key] ?? (opts?.defaultValue as string | undefined) ?? key;
        if (typeof tpl === 'string' && opts && 'count' in opts) {
          return tpl.replace('{{count}}', String(opts.count));
        }
        return tpl;
      },
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/api/modules/memory', () => ({
  memoryApi: { forgetEpisode: vi.fn() },
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryGovernancePage />
  </MemoryRouter>
);

beforeEach(() => vi.clearAllMocks());

describe('MemoryGovernancePage', () => {
  it('renders developer-view links pointing to legacy layer pages', async () => {
    renderPage();
    await waitFor(() => screen.getByText('原始事件 (L1)'));
    expect(screen.getByRole('link', { name: '原始事件 (L1)' })).toHaveAttribute('href', '/memory/events');
    expect(screen.getByRole('link', { name: '结构化知识 (L2)' })).toHaveAttribute('href', '/memory/knowledge');
    expect(screen.getByRole('link', { name: '工具技能 (L4)' })).toHaveAttribute('href', '/memory/skills');
  });

  it('does not render the pending-review section', () => {
    renderPage();
    expect(screen.queryByTestId('governance-pending-count')).not.toBeInTheDocument();
  });
});
