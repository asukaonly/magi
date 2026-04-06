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

describe('memory page design', () => {
  beforeEach(() => {
    mockUseMemory.mockReturnValue({
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
        trace: {},
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
    } as any);
  });

  it('renders the overview as a mixed dashboard with layer access and recent changes', () => {
    render(
      <MemoryRouter>
        <MemoryOverviewPage />
      </MemoryRouter>
    );

    expect(screen.getByTestId('memory-theme-root').className).toContain('memory-theme-surface');
    expect(screen.queryByTestId('memory-page-hero')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-page-header')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-layer-grid')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-recent-changes')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-signal-strip')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-search-results')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-recommended-layers')).toBeInTheDocument();
    expect(screen.getByText('app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari')).toBeInTheDocument();
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
