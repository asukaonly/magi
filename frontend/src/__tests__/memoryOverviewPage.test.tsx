import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryOverviewPage } from '@/pages/memory-pages';
import { memoryApi } from '@/api/modules/memory';
import { sensorsApi } from '@/api/modules/sensors';
import { memoryStoriesApi } from '@/api/modules/memoryStories';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (options && typeof options.count === 'number') {
        return `${key}:${options.count}`;
      }
      return key;
    },
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/api/modules/memory', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/memory')>('@/api/modules/memory');
  return {
    ...actual,
    memoryApi: {
      getDashboard: vi.fn(),
      submitAssertionFeedback: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/sensors', () => ({
  sensorsApi: {
    getStatus: vi.fn(),
  },
}));

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: {
    list: vi.fn(),
    review: vi.fn(),
  },
}));

const dashboardPayload = {
  statistics: {
    l0: { active_sessions: 0, total_goals: 0, total_entities: 0, total_tactics: 0 },
    l1: { event_count: 12 },
    l2: { relation_count: 4, assertion_count: 6 },
    l3: { summary_count: 5 },
    l4: { skill_count: 1, open_circuit_breakers: 0 },
    total_memories: 28,
    disk_usage_bytes: 1536,
    attention: { pending_assertions: 1, open_circuit_breakers: 0 },
  },
  source_counts: [
    {
      source: 'chrome-history',
      event_count: 9,
      avg_importance: 0.6,
      first_event_at: 1710000000,
      last_event_at: 1710003600,
    },
    {
      source: 'chat',
      event_count: 3,
      avg_importance: 0.8,
      first_event_at: 1710000100,
      last_event_at: 1710000200,
    },
  ],
  attention: { pending_assertions: 1, open_circuit_breakers: 0 },
  pending_assertions: {
    items: [
      {
        assertion_id: 'assert-1',
        entity_id: 'user:self',
        entity_type: 'user',
        trait_family: 'preference_profile',
        trait_name: 'favorite_language',
        trait_value: 'Python',
        confidence_score: 0.3,
        evidence_events: ['evt-1'],
        validation_state: 'tentative',
        volatility_index: 0.4,
        source_domain: 'conversation',
        inference_depth: 'semantic',
        first_inferred_at: 1710000000,
        last_validated_at: 1710000000,
        user_feedback: null,
        user_feedback_at: null,
        status: 'tentative',
      },
    ],
    total: 1,
    limit: 8,
    offset: 0,
  },
};

const storyPayload = {
  items: [
    {
      summary_id: 'story-1',
      summary_type: 'insight',
      summary_category: 'state_change',
      title: 'Sleep changed',
      content: 'Your sleep pattern looks different this week.',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003600,
      review_state: 'pending_confirmation',
      insight_key: 'state:sleep',
      insight_metadata: {},
      evidence_event_count: 4,
    },
    {
      summary_id: 'story-2',
      summary_type: 'temporal',
      summary_category: 'day',
      title: 'Yesterday',
      content: 'A normal day.',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003500,
      review_state: 'neutral',
      insight_key: null,
      insight_metadata: {},
      evidence_event_count: 2,
    },
  ],
  total: 2,
  limit: 12,
  offset: 0,
};

const sensorPayload = {
  sources: [
    {
      source_name: 'chrome-history',
      plugin_id: 'chrome-history',
      contribution_id: 'chrome-history',
      display_name: 'Chrome History',
      display_name_translated: 'Chrome History',
      description: '',
      fields: [],
      current_settings: {},
      enabled: true,
      sync_mode: 'manual',
      sync_interval_minutes: 60,
      storage_mode: 'local',
      fetch_page_content: false,
      edge_whitelist: [],
      supports_pull_sync: true,
      running: false,
      last_result_count: 2,
      last_sync_at: 1710003600,
    },
  ],
};

describe('MemoryOverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(memoryApi.getDashboard).mockResolvedValue(dashboardPayload as any);
    vi.mocked(sensorsApi.getStatus).mockResolvedValue(sensorPayload as any);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(storyPayload as any);
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue(dashboardPayload.pending_assertions.items[0] as any);
    vi.mocked(memoryStoriesApi.review).mockResolvedValue({
      ok: true,
      summary_id: 'story-1',
      review_state: 'confirmed',
    });
  });

  it('renders dashboard metrics, source coverage, pending review, and recent memory', async () => {
    render(<MemoryOverviewPage />);

    expect(await screen.findByText('28')).toBeInTheDocument();
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();
    expect(screen.getByText('Chrome History')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('chat')).toBeInTheDocument();
    expect(screen.getByText('favorite_language')).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('Sleep changed')).toBeInTheDocument();
    expect(screen.getByText('Yesterday')).toBeInTheDocument();
    expect(memoryApi.getDashboard).toHaveBeenCalledWith({ pending_limit: 8 });
    expect(sensorsApi.getStatus).toHaveBeenCalled();
    expect(memoryStoriesApi.list).toHaveBeenCalledWith({ limit: 12, offset: 0 });
  });

  it('routes pending item actions to their owning memory APIs', async () => {
    const user = userEvent.setup();
    render(<MemoryOverviewPage />);

    await screen.findByText('favorite_language');
    await user.click(screen.getByRole('button', { name: 'memory.overview.actions.confirmAssertion' }));

    expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');

    await waitFor(() => {
      expect(screen.queryByText('favorite_language')).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'memory.overview.actions.confirmStory' }));

    expect(memoryStoriesApi.review).toHaveBeenCalledWith('story-1', { review_state: 'confirmed' });
  });
});
