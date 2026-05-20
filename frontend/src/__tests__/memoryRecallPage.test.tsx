import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryRecallPage } from '@/pages/memory-pages/MemoryRecallPage';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.recall.title': '回忆',
    'memory.recall.subtitle': '用自然语言把过去翻出来',
    'memory.recall.searchPlaceholder': '想找一段对话…',
    'memory.recall.advancedToggle': '调试细节',
    'memory.recall.noResults': '没找到合适的记忆',
    'memory.recall.modes.auto': '智能',
    'memory.recall.modes.events': '你说过 / 做过的事',
    'memory.recall.modes.knowledge': '一句具体的事实',
    'memory.recall.modes.state': '你现在的状态',
    'memory.recall.modes.episodes': '一段经历',
    'memory.recall.modes.summaries': 'Magi 的总结',
    'memory.recall.modes.skills': 'Magi 学到的做事方式',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: { defaultValue?: string }) => labels[key] ?? opts?.defaultValue ?? key,
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/hooks/useMemory');

const renderPage = () => render(
  <MemoryRouter>
    <MemoryRecallPage />
  </MemoryRouter>
);

beforeEach(() => {
  vi.mocked(useMemory).mockReturnValue({
    loading: false,
    stats: { l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
    searchQuery: '',
    setSearchQuery: vi.fn(),
    searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
    searching: false,
    handleSearch: vi.fn(),
    refreshAll: vi.fn(),
  } as unknown as ReturnType<typeof useMemory>);
});

describe('MemoryRecallPage', () => {
  it('does not show storage stats in the header', () => {
    renderPage();
    expect(screen.queryByText(/记忆条数|占用大小/)).not.toBeInTheDocument();
  });

  it('hides diagnostics panel until disclosure is toggled', async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByTestId('memory-recall-diagnostics')).not.toBeInTheDocument();
    await user.click(screen.getByText('调试细节'));
    expect(screen.getByTestId('memory-recall-diagnostics')).toBeInTheDocument();
  });
});
