import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { MemoryKnowledgePage } from '@/pages/memory-pages/MemoryKnowledgePage';
import { useMemory } from '@/hooks/useMemory';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/hooks/useMemory', () => ({
  useMemory: vi.fn(),
}));

const mockUseMemory = vi.mocked(useMemory);

const createMemoryStub = () =>
  ({
    loading: false,
    l1Events: [
      {
        event_id: 'evt-1',
        event_type: 'conversation',
        content: 'User said West Lake feels calm.',
        source: 'user',
        author_type: 'user',
        content_type: 'text',
        user_id: 'web_user',
      },
    ],
    l2Relations: [
      {
        triple_id: 'rel-1',
        subject_id: 'entity-user',
        subject_type: 'person',
        predicate: 'likes',
        object_id: 'entity-west-lake',
        object_type: 'place',
        confidence: 0.91,
        status: 'active',
      },
    ],
    l2Assertions: [
      {
        assertion_id: 'assert-1',
        entity_id: 'entity-user',
        entity_type: 'person',
        trait_name: 'preference',
        trait_value: 'calm water',
        validation_state: 'accepted',
      },
    ],
    l2Stats: {
      relation_count: 1,
      assertion_count: 1,
      extract_skipped: 0,
      extract_by_evidence_class: { direct_statement: 1 },
      skip_by_reason: { none: 1 },
      canonical_self_id: 'user:self',
      identity_link_count: 1,
    },
    identityLinks: [
      {
        namespace: 'runtime',
        runtime_user_id: 'web_user',
        memory_owner_id: 'user:self',
      },
    ],
    l2Entities: [
      {
        entity_id: 'entity-west-lake',
        canonical_name: 'West Lake',
        entity_type: 'place',
        aliases: ['Xihu'],
      },
    ],
    l2Mentions: [
      {
        mention_id: 'mention-1',
        mention_text: 'West Lake',
        resolved_entity_id: 'entity-west-lake',
        entity_type: 'place',
        evidence_text: 'Mentioned during conversation',
      },
    ],
    l2Snapshots: [
      {
        snapshot_id: 'snapshot-1',
        entity_id: 'entity-west-lake',
        entity_type: 'place',
        current_mood: 'calm',
        core_traits: { vibe: 'gentle' },
      },
    ],
    l2ConflictRules: [
      {
        predicate: 'likes',
        opposite_predicates: ['dislikes'],
        exclusive_group: 'preference',
      },
    ],
    l2ActionLoading: false,
    submitManualL2Event: vi.fn(),
    replayL2Extraction: vi.fn(),
    runL2Reconcile: vi.fn(),
    runL2SnapshotRefresh: vi.fn(),
    upsertL2GraphConflictRule: vi.fn(),
    refresh: vi.fn(),
  }) as any;

describe('memory knowledge page tabs', () => {
  beforeEach(() => {
    mockUseMemory.mockReturnValue(createMemoryStub());
  });

  it('renders in-page tabs and switches knowledge sections without stacking all modules together', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <MemoryKnowledgePage />
      </MemoryRouter>
    );

    expect(screen.getByRole('tablist')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'memory.pages.knowledge.tabs.overview' })).toHaveAttribute(
      'data-state',
      'active'
    );
    expect(screen.getByTestId('memory-knowledge-tab-panel-overview')).toBeInTheDocument();
    expect(screen.getByTestId('memory-knowledge-tab-panel-lab')).not.toBeVisible();

    await user.click(screen.getByRole('tab', { name: 'memory.pages.knowledge.tabs.lab' }));

    expect(screen.getByTestId('memory-knowledge-tab-panel-lab')).toBeInTheDocument();
    expect(screen.getByTestId('memory-knowledge-tab-panel-overview')).not.toBeVisible();
    expect(screen.getByText('memory.l2.lab.title')).toBeInTheDocument();
  });

  it('moves filters under the knowledge-graph tab and applies them to the relation list', async () => {
    const user = userEvent.setup();

    mockUseMemory.mockReturnValue({
      ...createMemoryStub(),
      loading: false,
      l2Relations: [
        {
          triple_id: 'rel-1',
          subject_id: 'entity-user',
          subject_type: 'person',
          predicate: 'likes',
          object_id: 'entity-west-lake',
          object_type: 'place',
          confidence: 0.91,
          observation_count: 2,
          status: 'active',
        },
        {
          triple_id: 'rel-2',
          subject_id: 'entity-user',
          subject_type: 'person',
          predicate: 'dislikes',
          object_id: 'entity-office',
          object_type: 'place',
          confidence: 0.6,
          observation_count: 1,
          status: 'conflicted',
        },
      ],
      l2Entities: [
        {
          entity_id: 'entity-west-lake',
          canonical_name: 'West Lake',
          entity_type: 'place',
          aliases: ['Xihu'],
        },
        {
          entity_id: 'entity-office',
          canonical_name: 'Office',
          entity_type: 'place',
          aliases: [],
        },
      ],
    } as any);

    render(
      <MemoryRouter>
        <MemoryKnowledgePage />
      </MemoryRouter>
    );

    expect(screen.queryByTestId('memory-page-filters')).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'memory.pages.knowledge.tabs.knowledgeGraph' }));

    expect(screen.getByTestId('memory-knowledge-graph-filters')).toBeInTheDocument();
    expect(screen.queryByText('memory.pages.knowledge.sections.graphFocus')).not.toBeInTheDocument();
    expect(screen.getByText('likes → entity-west-lake')).toBeInTheDocument();
    expect(screen.getByText('dislikes → entity-office')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('memory.pages.knowledge.graphFilters.status'), 'conflicted');

    expect(screen.queryByText('likes → entity-west-lake')).not.toBeInTheDocument();
    expect(screen.getByText('dislikes → entity-office')).toBeInTheDocument();
  });
});
