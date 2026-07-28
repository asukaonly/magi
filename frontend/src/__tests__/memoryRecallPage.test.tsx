import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

import { MemoryRecallPage } from '@/pages/memory-pages/MemoryRecallPage';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.recall.title': '回忆',
    'memory.recall.subtitle': '用自然语言把过去翻出来',
    'memory.recall.searchPlaceholder': '想找一段对话…',
    'memory.recall.emptyStateIntro': 'magi 对你的了解还很有限',
    'memory.recall.manualEntry': '手动添加一条记忆',
    'memory.recall.advancedToggle': '调试细节',
    'memory.recall.noResults': '没找到合适的记忆',
    'memory.recall.searching': '正在找相关记忆',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: { defaultValue?: string }) => labels[key] ?? opts?.defaultValue ?? key,
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/hooks/useMemory');
vi.mock('@/components/empty-state/EmptyStateAvailableSensors', () => ({
  EmptyStateAvailableSensors: () => <div data-testid="available-sensors" />,
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryRecallPage />
  </MemoryRouter>
);

beforeEach(() => {
  vi.mocked(useMemory).mockReturnValue({
    loading: false,
    stats: { total_memories: 0, l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
    searchQuery: '',
    setSearchQuery: vi.fn(),
    searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
    searching: false,
    handleSearch: vi.fn(),
    refreshAll: vi.fn(),
  } as unknown as ReturnType<typeof useMemory>);
});

describe('MemoryRecallPage', () => {
  it('does not render the page header card', () => {
    renderPage();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.queryByText('回忆')).not.toBeInTheDocument();
  });

  it('shows the cold-start guide when there are no memories yet', () => {
    renderPage();
    expect(screen.getByText('magi 对你的了解还很有限')).toBeInTheDocument();
    expect(screen.getByTestId('available-sensors')).toBeInTheDocument();
    expect(screen.getByText('手动添加一条记忆')).toBeInTheDocument();
  });

  it('hides the cold-start guide when overview stats already include memories', () => {
    vi.mocked(useMemory).mockReturnValue({
      loading: false,
      stats: {
        total_memories: 12,
        l1: { event_count: 8 },
        l2: { relation_count: 1, assertion_count: 2 },
        l3: { summary_count: 1 },
        l4: { skill_count: 0 },
      },
      searchQuery: '',
      setSearchQuery: vi.fn(),
      searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
      searching: false,
      handleSearch: vi.fn(),
      refreshAll: vi.fn(),
    } as unknown as ReturnType<typeof useMemory>);

    renderPage();

    expect(screen.queryByText('magi 对你的了解还很有限')).not.toBeInTheDocument();
    expect(screen.queryByTestId('available-sensors')).not.toBeInTheDocument();
    expect(screen.queryByText('手动添加一条记忆')).not.toBeInTheDocument();
  });

  it('renders returned memory search results', () => {
    vi.mocked(useMemory).mockReturnValue({
      loading: false,
      stats: { total_memories: 0, l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
      searchQuery: '东京',
      setSearchQuery: vi.fn(),
      searchResults: {
        l1_events: [
          {
            event_id: 'evt-1',
            content: '在东京站附近看到了很安静的夜景',
            source_type: 'manual',
          },
        ],
        l2_relationships: [],
        l2_entity_cards: [],
        l3_reflections: [],
        l4_procedures: [],
        trace: {},
      },
      searching: false,
      handleSearch: vi.fn(),
      refreshAll: vi.fn(),
    } as unknown as ReturnType<typeof useMemory>);

    renderPage();

    expect(screen.getByText('在东京站附近看到了很安静的夜景')).toBeInTheDocument();
  });

  it('searches without exposing a manual mode selector', async () => {
    const handleSearch = vi.fn();
    vi.mocked(useMemory).mockReturnValue({
      loading: false,
      stats: { total_memories: 0, l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
      searchQuery: '东京',
      setSearchQuery: vi.fn(),
      searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
      searching: false,
      handleSearch,
      refreshAll: vi.fn(),
    } as unknown as ReturnType<typeof useMemory>);

    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByLabelText('回忆')).not.toBeInTheDocument();
    const searchSection = screen.getByTestId('memory-recall-search');
    const searchButton = searchSection.querySelector('button.bg-primary');
    expect(searchButton).toBeInstanceOf(HTMLButtonElement);
    await user.click(searchButton as HTMLButtonElement);
    expect(handleSearch).toHaveBeenCalledWith();
  });

  it('shows progress instead of no results while a search is pending', async () => {
    const handleSearch = vi.fn();
    let memoryState = {
      loading: false,
      stats: { total_memories: 5, l1: { event_count: 3 }, l2: { relation_count: 1, assertion_count: 1 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
      searchQuery: '我听过的歌',
      setSearchQuery: vi.fn(),
      searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
      searching: false,
      handleSearch,
      refreshAll: vi.fn(),
    } as unknown as ReturnType<typeof useMemory>;
    vi.mocked(useMemory).mockImplementation(() => memoryState);

    const user = userEvent.setup();
    const { rerender } = renderPage();
    const searchSection = screen.getByTestId('memory-recall-search');
    const searchButton = searchSection.querySelector('button.bg-primary');

    await user.click(searchButton as HTMLButtonElement);
    memoryState = { ...memoryState, searching: true } as ReturnType<typeof useMemory>;
    rerender(
      <MemoryRouter>
        <MemoryRecallPage />
      </MemoryRouter>
    );

    expect(screen.queryByText('没找到合适的记忆')).not.toBeInTheDocument();
    expect(screen.getByText('正在找相关记忆')).toBeInTheDocument();
  });

  it('hides diagnostics panel until disclosure is toggled', async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByTestId('memory-recall-diagnostics')).not.toBeInTheDocument();
    await user.click(screen.getByText('调试细节'));
    expect(screen.getByTestId('memory-recall-diagnostics')).toBeInTheDocument();
  });
});
