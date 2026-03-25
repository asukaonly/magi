import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { MemoryEventsPage } from '@/pages/memory-pages/MemoryEventsPage';
import { MemoryKnowledgePage } from '@/pages/memory-pages/MemoryKnowledgePage';
import { MemoryOverviewPage } from '@/pages/memory-pages/MemoryOverviewPage';
import { MemoryReflectionPage } from '@/pages/memory-pages/MemoryReflectionPage';
import { MemorySkillsPage } from '@/pages/memory-pages/MemorySkillsPage';
import { MemoryWorkbenchPage } from '@/pages/memory-pages/MemoryWorkbenchPage';
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

vi.mock('@/components/memory', async () => {
  const actual = await vi.importActual<typeof import('@/components/memory')>('@/components/memory');
  return {
    ...actual,
    ClearMemoryDialog: () => null,
    L0Tab: () => <div data-testid="l0-tab">l0-tab</div>,
    L1Tab: () => <div data-testid="l1-tab">l1-tab</div>,
    L2Tab: () => <div data-testid="l2-tab">l2-tab</div>,
    L3Tab: () => <div data-testid="l3-tab">l3-tab</div>,
    L4Tab: () => <div data-testid="l4-tab">l4-tab</div>,
  };
});

const mockUseMemory = vi.mocked(useMemory);

const memoryStub = {
  loading: false,
  stats: {
    l0: { active_sessions: 1, total_goals: 0, total_entities: 0, total_tactics: 0 },
    l1: { event_count: 1 },
    l2: { relation_count: 1, assertion_count: 1 },
    l3: { summary_count: 1 },
    l4: { skill_count: 1, open_circuit_breakers: 0 },
  },
  l0Sessions: [],
  l0Workbench: null,
  selectedSessionId: null,
  selectSession: vi.fn(),
  l1Events: [],
  l2Relations: [],
  l2Assertions: [],
  l2Stats: { relation_count: 1, assertion_count: 1 },
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
} as any;

describe('memory page loading scopes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMemory.mockReturnValue(memoryStub);
  });

  it('wires each memory route to its page-specific initial load scope', () => {
    render(
      <MemoryRouter>
        <div>
          <MemoryOverviewPage />
          <MemoryWorkbenchPage />
          <MemoryEventsPage />
          <MemoryKnowledgePage />
          <MemoryReflectionPage />
          <MemorySkillsPage />
        </div>
      </MemoryRouter>
    );

    expect(mockUseMemory).toHaveBeenCalledWith({ initialLoadScope: 'overview' });
    expect(mockUseMemory).toHaveBeenCalledWith({ initialLoadScope: 'l0' });
    expect(mockUseMemory).toHaveBeenCalledWith({ initialLoadScope: 'l1' });
    expect(mockUseMemory).toHaveBeenCalledWith({ initialLoadScope: 'l2' });
    expect(mockUseMemory).toHaveBeenCalledWith({ initialLoadScope: 'l3' });
    expect(mockUseMemory).toHaveBeenCalledWith({ initialLoadScope: 'l4' });
  });
});
