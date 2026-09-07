import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';

import { MemoryRecallPage } from '@/pages/memory-pages/MemoryRecallPage';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => {
  const labels: Record<string, string> = {
    'memory.recall.title': '回忆',
    'memory.facts.unavailable': '完整事实暂不可用',
    'memory.governance.statuses.needsReview': '待确认',
    'memory.governance.statuses.active': '有效',
    'memory.sources.user_authored': '你写下的内容',
    'memory.l1.domains.user_authored': '用户写入',
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
vi.mock('@/components/empty-state/EmptyStateAvailableSources', () => ({
  EmptyStateAvailableSources: () => <div data-testid="available-sources" />,
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryRecallPage />
  </MemoryRouter>
);

beforeEach(() => {
  vi.mocked(useMemory).mockReturnValue({
    loading: false,
    stats: { stored_records: 0, l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
    searchQuery: '',
    setSearchQuery: vi.fn(),
    searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
    searching: false,
    handleSearch: vi.fn(),
    refreshAll: vi.fn(),
  } as unknown as ReturnType<typeof useMemory>);
});

describe('MemoryRecallPage', () => {
  it('shows a retryable error instead of an empty-result claim', async () => {
    const original = vi.mocked(useMemory)();
    const handleSearch = vi.fn();
    vi.mocked(useMemory).mockReturnValue({ ...original, searchError: true, handleSearch });
    renderPage();
    expect(screen.getByRole('alert')).toHaveTextContent('memory.recall.searchFailed');
    expect(screen.queryByText('没找到合适的记忆')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(handleSearch).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'common.search' })).toBeInTheDocument();
  });

  it('does not render the page header card', () => {
    renderPage();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.queryByText('回忆')).not.toBeInTheDocument();
  });

  it('shows the cold-start guide when there are no memories yet', () => {
    renderPage();
    expect(screen.getByText('magi 对你的了解还很有限')).toBeInTheDocument();
    expect(screen.getByTestId('available-sources')).toBeInTheDocument();
    expect(screen.getByText('手动添加一条记忆')).toBeInTheDocument();
  });

  it('hides the cold-start guide when overview stats already include memories', () => {
    vi.mocked(useMemory).mockReturnValue({
      loading: false,
      stats: {
        stored_records: 12,
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
    expect(screen.queryByTestId('available-sources')).not.toBeInTheDocument();
    expect(screen.queryByText('手动添加一条记忆')).not.toBeInTheDocument();
  });

  it('renders returned memory search results', () => {
    vi.mocked(useMemory).mockReturnValue({
      loading: false,
      stats: { stored_records: 0, l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
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
      stats: { stored_records: 0, l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
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
      stats: { stored_records: 5, l1: { event_count: 3 }, l2: { relation_count: 1, assertion_count: 1 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
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


describe('assertion recall display', () => {
  const showAssertions = (items: Array<Record<string, unknown>>, field = 'l2_assertions') => {
    const current = vi.mocked(useMemory)();
    vi.mocked(useMemory).mockReturnValue({
      ...current,
      stats: { ...current.stats, stored_records: items.length },
      searchResults: { ...current.searchResults, [field]: items },
    });
    return renderPage();
  };

  it.each([
    ['喜欢', { natural_summary: '用户喜欢草莓。' }, '用户喜欢草莓。'],
    ['不喜欢', { trait_value: 'dislike', natural_summary: '用户不喜欢草莓。' }, '用户不喜欢草莓。'],
    ['兴趣', { trait_name: 'interest.topic', trait_value: 'interest', display_text: '用户对摄影感兴趣。' }, '用户对摄影感兴趣。'],
    ['称呼', { trait_name: 'communication.address.preferred', trait_value: '小涵', display_text: '用户希望被称为小涵。' }, '用户希望被称为小涵。'],
    ['近期偏好', { temporal_scope: 'recent', display_text: '用户最近喜欢草莓。' }, '用户最近喜欢草莓。'],
    ['摘要缺失', { display_text: '用户喜欢草莓。' }, '用户喜欢草莓。'],
    ['实体未解析', { target_entity_name: null, display_text: '用户表达了喜欢，但具体对象暂不可用。' }, '用户表达了喜欢，但具体对象暂不可用。'],
    ['完整描述缺失', {}, '完整事实暂不可用'],
  ] as const)('renders %s from the fact contract and keeps internal values out of the result', (_name, override, expected) => {
    showAssertions([{
      assertion_id: 'assert_f0246f5594db404196b430b6bc9a5ab4',
      entity_id: 'user:self',
      trait_name: 'preference.affinity',
      trait_value: 'like',
      value: 'like',
      target_entity_id: 'entity-strawberry',
      target_entity_name: '草莓',
      source: 'user_authored',
      memory_domain: 'user_authored',
      status: 'tentative',
      ...override,
    }]);
    expect(screen.getByRole('heading', { name: expected })).toBeInTheDocument();
    expect(screen.getByText('待确认')).toBeInTheDocument();
    expect(screen.queryByText('like')).not.toBeInTheDocument();
    expect(screen.queryByText('dislike')).not.toBeInTheDocument();
    expect(screen.queryByText('user_authored')).not.toBeInTheDocument();
    expect(screen.queryByText('tentative')).not.toBeInTheDocument();
    expect(screen.queryByText('entity-strawberry')).not.toBeInTheDocument();
  });

  it('preserves every concrete object and prioritizes the host display over an older summary', () => {
    showAssertions([
      { assertion_id: 'strawberry', trait_value: 'like', natural_summary: '用户喜欢草莓。', display_text: '用户最近喜欢草莓。' },
      { assertion_id: 'blueberry', trait_value: 'like', natural_summary: '用户喜欢蓝莓。' },
    ]);
    expect(screen.getByRole('heading', { name: '用户最近喜欢草莓。' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '用户喜欢蓝莓。' })).toBeInTheDocument();
    expect(screen.queryByText('用户喜欢草莓。')).not.toBeInTheDocument();
  });

  it('uses the same assertion presentation in structured result groups', () => {
    showAssertions([{ assertion_id: 'strawberry', trait_value: 'like', value: 'like', display_text: '用户喜欢草莓。' }], 'structured_results');
    expect(screen.getByRole('heading', { name: '用户喜欢草莓。' })).toBeInTheDocument();
    expect(screen.queryByText('like')).not.toBeInTheDocument();
  });
});
