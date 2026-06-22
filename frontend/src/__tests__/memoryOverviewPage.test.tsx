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
      const translations: Record<string, string> = {
        'memory.overview.metrics.totalMemories': 'Total memories',
        'memory.overview.metrics.understanding': 'About you',
        'memory.overview.metrics.summaries': 'Reviews & summaries',
        'memory.overview.metrics.storage': 'Storage',
        'memory.overview.metricDelta.current': 'Current',
        'memory.overview.sections.sources': 'Source coverage',
        'memory.overview.sections.pending': 'Pending review',
        'memory.overview.sections.recent': 'Latest summaries',
        'memory.overview.sourceColumns.source': 'Source',
        'memory.overview.sourceColumns.status': 'Status',
        'memory.overview.sourceColumns.events': 'Stored',
        'memory.overview.sourceColumns.sync': 'Sync',
        'memory.overview.sourceStatus.ready': 'Normal',
        'memory.overview.sourceStatus.running': 'Syncing',
        'memory.overview.sourceStatus.stale': 'Delayed',
        'memory.overview.sourceStatus.error': 'Error',
        'memory.overview.sourceStatus.never_synced': 'Never synced',
        'memory.overview.sourceStatus.setup_required': 'Setup required',
        'memory.overview.sourceStatus.disabled': 'Disabled',
        'memory.sources.chat_projector': 'Chat',
        'timeline.sources.chat': 'Chat',
        'memory.stories.categories.day': 'Daily summary',
      };
      if (translations[key]) {
        return translations[key];
      }
      if (key === 'memory.overview.metricDelta.today') {
        return `Today +${options?.value ?? 0}`;
      }
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
      source: 'chat_projector',
      event_count: 3,
      avg_importance: 0.8,
      first_event_at: 1710000100,
      last_event_at: 1710000200,
    },
  ],
  processing_backlog: {
    all_idle: false,
    total_pending: 5,
    l2: {
      extract_pending: 2,
      reconcile_pending: 1,
      snapshot_pending: 1,
      projection_pending: 1,
      projection_claimed: 1,
      projection_failed: 0,
    },
    l1_embeddings: { pending: 0, worker_running: false, vector_enabled: false, async_embeddings: false },
    l3_embeddings: { pending: 1, worker_running: true, vector_enabled: true, async_embeddings: true },
    l4_embeddings: { pending: 0, worker_running: false, vector_enabled: false, async_embeddings: false },
  },
  deltas: {
    today: {
      total_memories: 9,
      l1_events: 4,
      l2_assertions: 3,
      l3_summaries: 2,
      disk_usage_bytes: null,
    },
  },
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
      title: '',
      content: 'A normal chat projector day.',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003500,
      review_state: 'neutral',
      insight_key: null,
      insight_metadata: {},
      evidence_event_count: 2,
    },
    {
      summary_id: 'story-duplicate',
      summary_type: 'temporal',
      summary_category: 'day',
      title: 'Yesterday copy',
      content: 'A normal chat projector day.',
      period_start: 1710000000,
      period_end: 1710003400,
      updated_at: 1710003400,
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
      icon: 'brand:googlechrome',
      description: '',
      fields: [],
      current_settings: {},
      enabled: true,
      status: 'ready',
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
    {
      source_name: 'screen-time',
      plugin_id: 'screen-time',
      contribution_id: 'screen-time',
      display_name: 'Screen Time',
      display_name_translated: 'Screen Time',
      icon: 'lucide:monitor',
      description: '',
      fields: [],
      current_settings: {},
      enabled: false,
      status: 'disabled',
      sync_mode: 'manual',
      sync_interval_minutes: 60,
      storage_mode: 'local',
      fetch_page_content: false,
      edge_whitelist: [],
      supports_pull_sync: true,
      running: false,
      last_result_count: 0,
      last_sync_at: null,
    },
    {
      source_name: 'safari-history',
      plugin_id: 'safari-history',
      contribution_id: 'safari-history',
      display_name: 'Safari History',
      display_name_translated: 'Safari History',
      icon: 'brand:safari',
      description: '',
      fields: [],
      current_settings: {},
      enabled: true,
      status: 'ready',
      sync_mode: 'manual',
      sync_interval_minutes: 60,
      storage_mode: 'local',
      fetch_page_content: false,
      edge_whitelist: [],
      supports_pull_sync: true,
      running: false,
      last_result_count: 0,
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

    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-theme-root')).toHaveClass('px-4', 'py-4');
    expect(screen.getByTestId('memory-theme-root')).not.toHaveClass('px-6', 'py-6');
    expect(await screen.findByText('Total memories')).toBeInTheDocument();
    expect(await screen.findByText('28')).toBeInTheDocument();
    expect(screen.getByText('Today +9')).toBeInTheDocument();
    expect(screen.getByText('About you')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('Today +3')).toBeInTheDocument();
    expect(screen.getByText('Reviews & summaries')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Today +2')).toBeInTheDocument();
    expect(screen.getByText('Storage')).toBeInTheDocument();
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();
    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.getByText('Source')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getAllByText('Stored').length).toBeGreaterThan(0);
    expect(screen.getByText('Sync')).toBeInTheDocument();
    expect(screen.getByText('memory.overview.processingBacklog:5')).toBeInTheDocument();
    expect(screen.getByText('Chrome History')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-icon-googlechrome')).toBeInTheDocument();
    expect(screen.getAllByText('Normal').length).toBeGreaterThan(0);
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.queryByText('Screen Time')).not.toBeInTheDocument();
    expect(screen.queryByText('Safari History')).not.toBeInTheDocument();
    expect(screen.queryByText('chat_projector')).not.toBeInTheDocument();
    expect(screen.getByText('favorite_language')).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('Sleep changed')).toBeInTheDocument();
    expect(screen.getByText('Latest summaries')).toBeInTheDocument();
    expect(screen.getByText('Daily summary')).toBeInTheDocument();
    expect(screen.getAllByText('A normal Chat day.')).toHaveLength(1);
    expect(screen.queryByText(/chat projector/i)).not.toBeInTheDocument();
    expect(memoryApi.getDashboard).toHaveBeenCalledWith({ pending_limit: 8 });
    expect(sensorsApi.getStatus).toHaveBeenCalled();
    expect(memoryStoriesApi.list).toHaveBeenCalledWith({ limit: 12, offset: 0 });
  });

  it('hides the pending section when nothing needs review', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      ...dashboardPayload,
      attention: { pending_assertions: 0, open_circuit_breakers: 0 },
      pending_assertions: { items: [], total: 0, limit: 8, offset: 0 },
    } as any);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      ...storyPayload,
      items: storyPayload.items.filter((story) => story.review_state !== 'pending_confirmation'),
    } as any);

    render(<MemoryOverviewPage />);

    expect(await screen.findByText('Latest summaries')).toBeInTheDocument();
    expect(screen.queryByText('Pending review')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.overview.empty.pending')).not.toBeInTheDocument();
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
