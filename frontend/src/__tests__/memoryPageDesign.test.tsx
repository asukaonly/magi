import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { MemoryOverviewPage } from '@/pages/memory-pages/MemoryOverviewPage';
import { MemoryWorkbenchPage } from '@/pages/memory-pages/MemoryWorkbenchPage';
import { MemoryEventsPage } from '@/pages/memory-pages/MemoryEventsPage';
import { MemoryReflectionPage } from '@/pages/memory-pages/MemoryReflectionPage';
import { useMemory } from '@/hooks/useMemory';

const TRANSLATION_MAP: Record<string, string> = {
  'memory.pages.reflection.types.temporal': 'Temporal',
  'memory.pages.reflection.types.thematic': 'Thematic',
  'memory.pages.reflection.types.insight': 'Insight',
  'memory.pages.reflection.categories.task_reflection': 'Task Reflection',
  'memory.search': 'Search',
  'memory.overview.searchResultsTitle': 'Search results',
  'memory.overview.searchOverviewTitle': 'Memory signals',
  'memory.overview.curatedEvidenceTitle': 'Curated evidence',
  'memory.overview.layeredResultsTitle': 'Layered results',
  'memory.overview.diagnosticsTitle': 'Retrieval diagnostics',
  'memory.overview.searchModes.auto.label': 'Smart',
  'memory.overview.searchModes.auto.description': 'Auto route',
  'memory.overview.searchModes.events.label': 'Events',
  'memory.overview.searchModes.events.description': 'Raw events',
  'memory.overview.searchModes.knowledge.label': 'Knowledge',
  'memory.overview.searchModes.knowledge.description': 'Facts',
  'memory.overview.searchModes.summaries.label': 'Summaries',
  'memory.overview.searchModes.summaries.description': 'Summaries',
  'memory.overview.searchModes.skills.label': 'Skills',
  'memory.overview.searchModes.skills.description': 'Skills',
  'memory.overview.searchModes.state.label': 'State',
  'memory.overview.searchModes.state.description': 'State',
  'memory.overview.searchModes.episodes.label': 'Episodes',
  'memory.overview.searchModes.episodes.description': 'Episodes',
  'memory.overview.queryModes.auto': 'Smart',
  'memory.overview.queryModes.event_stream': 'Event stream',
  'memory.overview.queryModes.exact_fact': 'Exact fact',
  'memory.overview.modeBadge': 'Mode',
  'memory.overview.requestedModeLabel': 'Requested',
  'memory.overview.resolvedModeLabel': 'Resolved',
  'memory.overview.executedLayersLabel': 'Executed',
  'memory.overview.noneValue': 'None',
  'memory.overview.resultKinds.event': 'Event',
  'memory.overview.resultKinds.entity': 'Entity',
  'memory.overview.resultKinds.reflection': 'Reflection',
  'memory.overview.totalMemoriesLabel': 'Memories',
  'memory.overview.diskUsageLabel': 'Storage',
  'memory.pages.events.resetButton': 'Reset',
  'memory.pages.reflection.cadenceTitle': 'Summary cadence',
  'memory.pages.reflection.topicsTitle': 'Topic fragments',
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => TRANSLATION_MAP[key] ?? key,
  }),
}));

vi.mock('@/hooks/useMemory', () => ({
  useMemory: vi.fn(),
  formatTimestamp: () => 'mock-time',
}));

vi.mock('@/components/memory', async () => {
  const actual = await vi.importActual<typeof import('@/components/memory')>('@/components/memory');
  return {
    ...actual,
    ClearMemoryDialog: () => null,
    L0Tab: () => <div data-testid="l0-tab">l0-tab</div>,
    L1Tab: () => <div data-testid="l1-tab">l1-tab</div>,
  };
});

const mockUseMemory = vi.mocked(useMemory);
let memoryState: any;

describe('memory page design', () => {
  beforeEach(() => {
    memoryState = {
      loading: false,
      stats: {
        l0: { active_sessions: 12, total_goals: 28, total_entities: 45, total_tactics: 8 },
        l1: { event_count: 248 },
        l2: { relation_count: 61, assertion_count: 14 },
        l3: { summary_count: 9 },
        l4: { skill_count: 6, open_circuit_breakers: 1 },
      },
      l0Sessions: [
        {
          session_id: 'session-alpha',
          user_id: 'local_user',
          status: 'active',
          started_at: 1710000000,
          last_active_at: 1710000300,
          goal_count: 3,
          entity_count: 5,
          tactic_count: 1,
        },
      ],
      l0Total: 1,
      l0Workbench: { session: { session_id: 'session-alpha' }, goal_stack: [], active_entities: [], temporary_tactics: [] },
      selectedSessionId: 'session-alpha',
      selectSession: vi.fn(),
      loadL0Sessions: vi.fn(),
      l1Events: [],
      l2Relations: [],
      l2Assertions: [],
      l2Stats: { relation_count: 61, assertion_count: 14 },
      identityLinks: [],
      l2Entities: [],
      l2Mentions: [],
      l2Snapshots: [],
      l2ConflictRules: [],
      l2ActionLoading: false,
      submitManualL2Event: vi.fn(),
      replayL2Extraction: vi.fn(),
      runL2Reconcile: vi.fn(),
      runL2SnapshotRefresh: vi.fn(),
      upsertL2GraphConflictRule: vi.fn(),
      l3Summaries: [
        {
          summary_id: 'sum-temporal',
          summary_type: 'temporal',
          summary_category: 'day',
          period_start: 1710000000,
          period_end: 1710003600,
          content: 'Daily planning focused on portfolio updates.',
          key_topics: ['portfolio'],
          key_entities: [],
          source_event_count: 3,
          created_at: 1710003600,
        },
        {
          summary_id: 'sum-thematic',
          summary_type: 'thematic',
          summary_category: 'topic',
          period_start: 1710000000,
          period_end: 1710086400,
          content: 'Career transition remained a recurring topic.',
          key_topics: ['career_switch'],
          key_entities: [{ entity_id: 'project:career-switch', entity_type: 'project' }],
          source_event_count: 5,
          created_at: 1710086400,
        },
        {
          summary_id: 'sum-insight',
          summary_type: 'insight',
          summary_category: 'task_reflection',
          period_start: 1710000000,
          period_end: 1710086400,
          content: 'The main blocker is still portfolio output, not direction clarity.',
          key_topics: ['career_switch', 'portfolio'],
          key_entities: [{ entity_id: 'project:career-switch', entity_type: 'project' }],
          source_event_count: 4,
          created_at: 1710086400,
        },
      ],
      l4Skills: [],
      searchResults: {
        l0_workbench: [],
        l1_events: [
          {
            event_id: 'evt-1',
            source_item_id: 'app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari',
            content: 'User mentioned a strong preference for calm lake walks',
            source: 'user',
            memory_domain: 'preference',
          },
        ],
        l2_entity_cards: [
          {
            entity_id: 'entity-west-lake',
            canonical_name: 'West Lake',
            entity_type: 'place',
          },
        ],
        l2_relationships: [],
        l3_reflections: [
          {
            summary_id: 'summary-1',
            content: 'Recent reflection highlights a preference for calm outdoor spaces.',
            summary_category: 'weekly',
          },
        ],
        l4_procedures: [],
        trace: {
          requested_query_mode: 'event_stream',
          resolved_query_mode: 'event_stream',
          executed_layers: ['L1'],
          layer_result_counts: { L1: 1, L2: 1, L3: 1, L4: 0 },
        },
      },
      searchQuery: '',
      setSearchQuery: vi.fn(),
      searching: false,
      handleSearch: vi.fn(),
      clearDialogOpen: false,
      setClearDialogOpen: vi.fn(),
      clearing: false,
      handleClearRequest: vi.fn(),
      handleClearConfirm: vi.fn(),
      refresh: vi.fn(),
      refreshAll: vi.fn(),
    } as any;
    mockUseMemory.mockImplementation(() => memoryState);
  });

  it('renders the overview as a focused dashboard with search and attention surfaces', () => {
    render(
      <MemoryRouter>
        <MemoryOverviewPage />
      </MemoryRouter>
    );

    expect(screen.getByTestId('memory-theme-root').className).toContain('memory-theme-surface');
    expect(screen.queryByTestId('memory-page-hero')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-page-header')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-stats')).toHaveTextContent('Memories');
    expect(screen.getByTestId('memory-overview-stats')).toHaveTextContent('338');
    expect(screen.getByTestId('memory-overview-stats')).toHaveTextContent('Storage');
    expect(screen.getByTestId('memory-overview-stats')).toHaveTextContent('0 B');
    expect(screen.getByTestId('memory-overview-search')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-search-modes')).toHaveTextContent('Smart');
    expect(screen.getByTestId('memory-overview-search-modes')).toHaveTextContent('Events');
    expect(screen.getByTestId('memory-overview-attention')).toBeInTheDocument();
    expect(screen.queryByTestId('memory-overview-search-results')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.refresh' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('memory.searchPlaceholder')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'memory.overview.openBreakers' })).toHaveAttribute('href', '/memory/skills');
  });

  it('renders search hits as readable memory previews instead of raw identifiers', () => {
    memoryState.searchQuery = 'lake';

    render(
      <MemoryRouter>
        <MemoryOverviewPage />
      </MemoryRouter>
    );

    expect(screen.getByTestId('memory-overview-search-results')).toHaveTextContent('Memory signals');
    expect(screen.getByTestId('memory-overview-search-results')).toHaveTextContent('Curated evidence');
    expect(screen.getByTestId('memory-overview-search-results')).toHaveTextContent('Layered results');
    expect(screen.getByTestId('memory-overview-search-results')).toHaveTextContent('Retrieval diagnostics');
    expect(screen.getByTestId('memory-overview-search-results')).toHaveTextContent('User mentioned a strong preference for calm lake walks');
    expect(screen.getByTestId('memory-overview-search-results')).toHaveTextContent('West Lake');
    expect(screen.getByTestId('memory-overview-search-results')).not.toHaveTextContent('app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari');
  });

  it('submits the selected workbench search mode', () => {
    render(
      <MemoryRouter>
        <MemoryOverviewPage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Events' }));
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(memoryState.handleSearch).toHaveBeenCalledWith('event_stream');
  });

  it('renders the workbench page as an operational layout without the shared hero shell', () => {
    render(
      <MemoryRouter>
        <MemoryWorkbenchPage />
      </MemoryRouter>
    );

    expect(screen.queryByTestId('memory-page-hero')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-page-header')).toBeInTheDocument();
    expect(screen.getByTestId('memory-page-filters')).toBeInTheDocument();
    expect(screen.getByText('memory.pages.workbench.sessionTitle')).toBeInTheDocument();
    expect(screen.getByTestId('l0-tab')).toBeInTheDocument();
  });

  it('renders the events page with source summary and stream access without a hero banner', () => {
    render(
      <MemoryRouter>
        <MemoryEventsPage />
      </MemoryRouter>
    );

    expect(screen.queryByTestId('memory-page-hero')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-page-header')).toBeInTheDocument();
    expect(screen.getByTestId('memory-page-filters')).toBeInTheDocument();
    expect(screen.getByTestId('memory-events-source-summary')).toBeInTheDocument();
    expect(screen.getByTestId('l1-tab')).toBeInTheDocument();
  });

  it('renders the reflection page as a type-driven workspace with tabs and insight category groups', () => {
    render(
      <MemoryRouter>
        <MemoryReflectionPage />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Temporal' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Thematic' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Insight' })).toBeInTheDocument();
    expect(screen.queryByText('Summary cadence')).not.toBeInTheDocument();
    expect(screen.queryByText('Topic fragments')).not.toBeInTheDocument();
    expect(screen.queryByText('Career transition remained a recurring topic.')).not.toBeInTheDocument();

    const temporalTab = screen.getByRole('tab', { name: 'Temporal' });
    const thematicTab = screen.getByRole('tab', { name: 'Thematic' });

    fireEvent.click(thematicTab);

    expect(temporalTab).toHaveAttribute('aria-selected', 'false');
    expect(thematicTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('memory.l3.summaryCount')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.reflection.cadenceBody')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.reflection.insightBody')).not.toBeInTheDocument();
  });
});
