import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import EventsPage from '@/pages/Events';
import { memoryApi } from '@/api/modules/memory';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    getStatistics: vi.fn(),
    getL0Sessions: vi.fn(),
    getL0Workbench: vi.fn(),
    getL1Events: vi.fn(),
    getL2Relations: vi.fn(),
    getL2Assertions: vi.fn(),
    getL2Statistics: vi.fn(),
    getL2Entities: vi.fn(),
    getL2Mentions: vi.fn(),
    getL2Snapshots: vi.fn(),
    getL2ConflictRules: vi.fn(),
    getL3Summaries: vi.fn(),
    getL4Skills: vi.fn(),
    search: vi.fn(),
    clearAll: vi.fn(),
    createManualL2Event: vi.fn(),
    replayL2Extraction: vi.fn(),
    reconcileL2Entities: vi.fn(),
    refreshL2Snapshots: vi.fn(),
    upsertL2ConflictRule: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

const L1_EVENT = {
  event_id: 'event-1',
  event_type: 'AI_RESPONSE',
  raw_content: 'hello',
  timestamp: 1710000000,
  source: 'assistant',
  memory_domain: 'interaction',
  retention_class: 'compressible',
  importance_score: 0.5,
  cognition_eligible: true,
};

describe('events page', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(memoryApi.getStatistics).mockResolvedValue({
      l0: { active_sessions: 1, total_goals: 0, total_entities: 0, total_tactics: 0 },
      l1: { event_count: 1 },
      l2: { relation_count: 0, assertion_count: 0 },
      l3: { summary_count: 0 },
      l4: { skill_count: 0, open_circuit_breakers: 0 },
    });
    vi.mocked(memoryApi.getL0Sessions).mockResolvedValue({
      sessions: [
        {
          session_id: 's1',
          user_id: 'u1',
          status: 'active',
          started_at: 1710000000,
          last_active_at: 1710000300,
          goal_count: 0,
          entity_count: 0,
          tactic_count: 0,
        },
      ],
      stats: { active_sessions: 1, total_goals: 0, total_entities: 0, total_tactics: 0 },
    });
    vi.mocked(memoryApi.getL0Workbench).mockResolvedValue({
      session: { session_id: 's1' },
      goal_stack: [],
      active_entities: [],
      temporary_tactics: [],
    });
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      events: [L1_EVENT],
      stats: { total: 1 },
    });
    vi.mocked(memoryApi.getL2Relations).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Assertions).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Statistics).mockResolvedValue({
      relation_count: 0,
      assertion_count: 0,
      extract_skipped: 0,
      extract_by_evidence_class: {},
      skip_by_reason: {},
    });
    vi.mocked(memoryApi.getL2Entities).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Mentions).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2Snapshots).mockResolvedValue([]);
    vi.mocked(memoryApi.getL2ConflictRules).mockResolvedValue([]);
    vi.mocked(memoryApi.getL3Summaries).mockResolvedValue([]);
    vi.mocked(memoryApi.getL4Skills).mockResolvedValue([]);
    vi.mocked(memoryApi.search).mockResolvedValue({
      success: true,
      message: 'ok',
      data: [],
    });
    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l0: { cleared: true, count: 1 },
        l1: { cleared: true, count: 2 },
        l2: { cleared: true, count: 3 },
        l3: { cleared: true, count: 4 },
        l4: { cleared: true, count: 5 },
        chat_context: { cleared: true, count: 6 },
      },
    });
  });

  it('renders event cards with proper structure', async () => {
    const user = userEvent.setup();
    render(<EventsPage />);

    await user.click(await screen.findByRole('tab', { name: 'L1' }));

    const eventTypeBadge = await screen.findByText('AI_RESPONSE');
    const eventCard = eventTypeBadge.closest('.rounded-lg');

    expect(eventCard).toBeInTheDocument();
    expect(eventCard).toHaveClass('rounded-lg');
  });

  it('opens the clear confirmation in a compact dialog container', async () => {
    const user = userEvent.setup();
    render(<EventsPage />);

    await user.click(await screen.findByRole('button', { name: 'memory.clear' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
  });
});
