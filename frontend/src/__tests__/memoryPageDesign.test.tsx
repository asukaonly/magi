import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { MemoryOverviewPage } from '@/pages/memory-pages/MemoryOverviewPage';
import { MemoryWorkbenchPage } from '@/pages/memory-pages/MemoryWorkbenchPage';
import { MemoryEventsPage } from '@/pages/memory-pages/MemoryEventsPage';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/hooks/useMemory', () => ({
  useMemory: vi.fn(),
  formatTimestamp: () => 'mock-time',
}));

vi.mock('@/components/memory', () => ({
  ClearMemoryDialog: () => null,
  L0Tab: () => <div data-testid="l0-tab">l0-tab</div>,
  L1Tab: () => <div data-testid="l1-tab">l1-tab</div>,
}));

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
          user_id: 'web_user',
          status: 'active',
          started_at: 1710000000,
          last_active_at: 1710000300,
          goal_count: 3,
          entity_count: 5,
          tactic_count: 1,
        },
      ],
      l0Workbench: { session: { session_id: 'session-alpha' }, goal_stack: [], active_entities: [], temporary_tactics: [] },
      selectedSessionId: 'session-alpha',
      selectSession: vi.fn(),
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
      l3Summaries: [],
      l4Skills: [],
      searchResults: {
        l0_workbench: [],
        l1_events: [
          {
            event_id: 'evt-1',
            raw_content: 'User mentioned a strong preference for calm lake walks',
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

    expect(screen.queryByTestId('memory-page-hero')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-page-header')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-layer-grid')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-recent-changes')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-signal-strip')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-search-results')).toBeInTheDocument();
    expect(screen.getByTestId('memory-overview-recommended-layers')).toBeInTheDocument();
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
});
