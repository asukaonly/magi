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

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/modules/memory')>();
  return {
    ...actual,
    memoryApi: {
      getStatistics: vi.fn(),
      getL0Sessions: vi.fn(),
      getL0Workbench: vi.fn(),
      getL1Events: vi.fn(),
      getL2Relations: vi.fn(),
      getL2Assertions: vi.fn(),
      getL2Statistics: vi.fn(),
      getIdentityLinks: vi.fn(),
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
  };
});

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

const L1_EVENT = {
  id: 101,
  event_id: 'event-1',
  source_item_id: 'chat_msg:turn-1:user',
  idempotency_key: 'chat:session-1:turn-1',
  event_type: 'AI_RESPONSE',
  content: 'hello',
  timestamp: 1710000000,
  source: 'assistant',
  memory_domain: 'interaction',
  retention_class: 'compressible',
  importance_score: 0.5,
  cognition_eligible: true,
  user_id: 'local_user',
  author_type: 'assistant',
  content_type: 'text',
};

describe('events page', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(memoryApi.getStatistics).mockResolvedValue({
      l0: { active_sessions: 1, total_attention_items: 1 },
      l1: { event_count: 1 },
      l2: { relation_count: 0, assertion_count: 0 },
      l3: { summary_count: 0 },
      l4: { skill_count: 0, open_circuit_breakers: 0 },
    });
    vi.mocked(memoryApi.getL0Sessions).mockResolvedValue({
      items: [
        {
          session_id: 's1',
          user_id: 'u1',
          status: 'active',
          started_at: 1710000000,
          last_active_at: 1710000300,
          attention_count: 1,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
      stats: { active_sessions: 1, total_attention_items: 1 },
    });
    vi.mocked(memoryApi.getL0Workbench).mockResolvedValue({
      session: { session_id: 's1' },
      attention_items: [{
        item_id: 'attention-1',
        kind: 'focus',
        summary: 'Discuss the current memory design',
        status: 'active',
        salience: 0.9,
        confidence: 0.95,
        evidence_mode: 'direct',
        source_turn_ids: ['turn-1'],
        source_event_ids: [],
        entity_id: null,
        task_id: null,
        first_seen_at: 1710000000,
        last_reinforced_at: 1710000300,
        expires_at: 1710086400,
        supersedes_item_id: null,
        metadata: {},
      }],
    });
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({
      items: [L1_EVENT],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(memoryApi.getL2Relations).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL2Assertions).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL2Statistics).mockResolvedValue({
      canonical_self_id: 'user:self',
      identity_link_count: 1,
      relation_count: 0,
      assertion_count: 0,
      extract_skipped: 0,
      extract_by_evidence_class: {},
      skip_by_reason: {},
    });
    vi.mocked(memoryApi.getIdentityLinks).mockResolvedValue({
      canonical_self_id: 'user:self',
      links: [
        {
          namespace: 'web',
          runtime_user_id: 'local_user',
          memory_owner_id: 'user:self',
          link_type: 'runtime_account',
        },
      ],
    });
    vi.mocked(memoryApi.getL2Entities).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL2Mentions).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL2Snapshots).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL2ConflictRules).mockResolvedValue([]);
    vi.mocked(memoryApi.getL3Summaries).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.getL4Skills).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(memoryApi.search).mockResolvedValue({
      l0_workbench: [],
      l1_events: [],
      l2_entity_cards: [],
      l2_relationships: [],
      l3_reflections: [],
      l4_procedures: [],
      trace: {},
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

  it('renders expandable event rows with audit details', async () => {
    const user = userEvent.setup();
    render(<EventsPage />);

    await user.click(await screen.findByRole('tab', { name: 'L1' }));

    await screen.findByText('AI_RESPONSE');
    expect(screen.getByText('hello')).toBeInTheDocument();

    await user.click(screen.getByText('hello'));

    expect(screen.getByText('memory.l1.technicalIdentifiers')).toBeInTheDocument();
    expect(screen.getByText('local_user')).toBeInTheDocument();
    expect(screen.queryByText('#101')).not.toBeInTheDocument();
    expect(screen.getByText(/chat_msg:turn-1:user/)).toBeInTheDocument();
  });

  it('opens the clear confirmation in a compact dialog container', async () => {
    const user = userEvent.setup();
    render(<EventsPage />);

    await user.click(await screen.findByRole('button', { name: 'memory.clear' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
  });
});
