import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

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

const mockUseMemory = vi.mocked(useMemory);

describe('MemoryEventsPage search interactions', () => {
  const queryL1Events = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMemory.mockReturnValue({
      loading: false,
      stats: {
        l0: { active_sessions: 0, total_attention_items: 0 },
        l1: { event_count: 2 },
        l2: { relation_count: 0, assertion_count: 0 },
        l3: { summary_count: 0 },
        l4: { skill_count: 0, open_circuit_breakers: 0 },
      },
      l0Sessions: [],
      l0Total: 0,
      l0Workbench: null,
      selectedSessionId: null,
      selectSession: vi.fn(),
      loadL0Sessions: vi.fn(),
      l1Events: [
        {
          event_id: 'evt-1',
          event_type: 'UserMessage',
          timestamp: 1710000000,
          content: 'West Lake walk notes',
          source: 'chat_projector',
          memory_domain: 'user_authored',
          retention_class: 'permanent',
          importance_score: 0.8,
          cognition_eligible: true,
          embedding_status: 'ready',
          embedding_profile_id: 'profile-a',
          embedding_chunk_count: 2,
          last_embedded_at: 1710000010,
          metadata_json: {
            timeline: {
              title: 'West Lake walk notes',
              source_app: 'Chat',
              provenance: {
                track_name: 'Heavenly Me',
                artist_name: 'AIYUE',
                album_name: 'Heavenly Me',
                play_duration_sec: 180,
              },
            },
            l2_batch_owner: 'chat_projector',
          },
        },
      ],
      l1Total: 1,
      queryL1Events,
      l2Relations: [],
      l2Assertions: [],
      l2Stats: { relation_count: 0, assertion_count: 0 },
      identityLinks: [],
      l2Entities: [],
      l2Mentions: [],
      l2Snapshots: [],
      l2ConflictRules: [],
      l2ActionLoading: false,
      submitManualL2Event: vi.fn(),
      replayL2Extraction: vi.fn(),
      flushL2Microbatches: vi.fn(),
      runL2Reconcile: vi.fn(),
      runL2SnapshotRefresh: vi.fn(),
      upsertL2GraphConflictRule: vi.fn(),
      submitAssertionFeedback: vi.fn(),
      l3Summaries: [],
      l4Skills: [],
      searchQuery: '',
      setSearchQuery: vi.fn(),
      searchResults: {
        l0_workbench: [],
        l1_events: [],
        l2_entity_cards: [],
        l2_relationships: [],
        l3_reflections: [],
        l4_procedures: [],
        trace: {},
      },
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

  it('only queries L1 when search or reset is clicked', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <MemoryEventsPage />
      </MemoryRouter>
    );

    await user.type(screen.getByLabelText('memory.pages.events.contentLabel'), 'lake');
    await user.type(screen.getByLabelText('memory.pages.events.startDateLabel'), '2026-03-01');
    await user.type(screen.getByLabelText('memory.pages.events.endDateLabel'), '2026-03-02');
    await user.click(screen.getByRole('button', { name: 'memory.filters.all' }));
    await user.click(screen.getByRole('button', { name: 'chat_projector' }));

    expect(queryL1Events).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'memory.search' }));

    expect(queryL1Events).toHaveBeenCalledWith({
      query: 'lake',
      source: 'chat_projector',
      start_date: '2026-03-01',
      end_date: '2026-03-02',
      offset: 0,
    });

    await user.click(screen.getByRole('button', { name: 'memory.pages.events.resetButton' }));

    expect(screen.getByLabelText('memory.pages.events.contentLabel')).toHaveValue('');
    expect(screen.getByLabelText('memory.pages.events.startDateLabel')).toHaveValue('');
    expect(screen.getByLabelText('memory.pages.events.endDateLabel')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'memory.filters.all' })).toBeInTheDocument();
    expect(queryL1Events).toHaveBeenLastCalledWith(undefined);
  });

  it('shows known source options even when the current result set is narrow', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <MemoryEventsPage />
      </MemoryRouter>
    );

    await user.click(screen.getByRole('button', { name: 'memory.filters.all' }));

    expect(screen.getByRole('button', { name: 'chat_projector' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'chrome_history' })).toBeInTheDocument();
  });

  it('shows compact header counts instead of statistic cards', () => {
    render(
      <MemoryRouter>
        <MemoryEventsPage />
      </MemoryRouter>
    );

    expect(screen.getByText('memory.l1.totalEvents')).toBeInTheDocument();
    expect(screen.getByText('memory.pages.events.matchedEventsLabel')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.queryByText('memory.l1.events')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.events.visibleEventsLabel')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.events.sourceSummaryTitle')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.events.domainSummaryTitle')).not.toBeInTheDocument();
  });

  it('expands a row to reveal event audit details', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <MemoryEventsPage />
      </MemoryRouter>
    );

    await user.click(screen.getByRole('button', { name: /memory\.l1\.toggleEventDetails/ }));

    expect(screen.getByText('memory.l1.sourceMetadata')).toBeInTheDocument();
    expect(screen.getByText('memory.l1.embeddingStatus')).toBeInTheDocument();
    expect(screen.getByText('ready')).toBeInTheDocument();
    expect(screen.getByText('Artist Name')).toBeInTheDocument();
    expect(screen.getByText('AIYUE')).toBeInTheDocument();
    expect(screen.getByText('Album Name')).toBeInTheDocument();
    expect(screen.getByText('memory.l1.rawMetadata')).toBeInTheDocument();
    expect(screen.getByText('memory.l1.technicalIdentifiers')).toBeInTheDocument();
  });

  it('passes through a single selected start date without forcing an end date', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <MemoryEventsPage />
      </MemoryRouter>
    );

    await user.type(screen.getByLabelText('memory.pages.events.startDateLabel'), '2026-03-28');
    await user.click(screen.getByRole('button', { name: 'memory.search' }));

    expect(queryL1Events).toHaveBeenCalledWith({
      start_date: '2026-03-28',
      end_date: undefined,
      offset: 0,
      query: undefined,
      source: undefined,
    });
  });
});
