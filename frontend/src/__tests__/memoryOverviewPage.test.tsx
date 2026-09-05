import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { MemoryOverviewPage } from '@/pages/memory-pages';
import { buildSourceRows } from '@/pages/memory-pages/overview/overviewModel';
import type { SourceStatusItem } from '@/api/modules/sources';
import { memoryApi } from '@/api/modules/memory';
import { sourcesApi } from '@/api/modules/sources';
import { memoryStoriesApi } from '@/api/modules/memoryStories';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const translations: Record<string, string> = {
        'memory.overview.metrics.sourceRecords': 'Source records',
        'memory.overview.metrics.profileCandidates': 'About you',
        'memory.overview.metrics.summaries': 'Reviews & summaries',
        'memory.overview.metrics.sources': 'Active sources',
        'memory.overview.metrics.storage': 'Storage',
        'memory.overview.summaryLabel': 'Memory summary',
        'memory.overview.metricDelta.current': 'Current',
        'memory.overview.sections.sources': 'Source coverage',
        'memory.overview.sections.pending': 'Pending review',
        'memory.overview.sections.recent': 'Latest summaries',
        'memory.overview.pendingKinds.review': 'Memory to confirm',
        'memory.overview.pendingKinds.assertion': 'Structured assertion',
        'memory.overview.pendingKinds.story': 'Memory update',
        'memory.overview.actions.confirm': 'Confirm',
        'memory.overview.actions.edit': 'Edit',
        'memory.overview.actions.reject': 'Not right',
        'memory.overview.actions.confirmReview': 'Confirm this memory',
        'memory.overview.actions.editReview': 'Edit and confirm',
        'memory.overview.actions.rejectReview': 'Do not use this memory',
        'memory.overview.actions.confirmAssertion': 'Confirm assertion',
        'memory.overview.actions.rejectAssertion': 'Reject assertion',
        'memory.overview.actions.confirmStory': 'Confirm memory update',
        'memory.overview.actions.rejectStory': 'Reject memory update',
        'memory.overview.sourceColumns.source': 'Source',
        'memory.overview.sourceColumns.status': 'Status',
        'memory.overview.sourceColumns.events': 'Stored',
        'memory.overview.sourceColumns.sync': 'Sync',
        'memory.overview.sourceStatus.ready': 'Normal',
        'memory.overview.sourceStatus.running': 'Syncing',
        'memory.overview.sourceStatus.retrying': 'Retrying',
        'memory.overview.sourceStatus.stale': 'Delayed',
        'memory.overview.sourceStatus.error': 'Error',
        'memory.overview.sourceStatus.never_synced': 'Never synced',
        'memory.overview.sourceStatus.setup_required': 'Setup required',
        'memory.overview.sourceStatus.disabled': 'Disabled',
        'memory.overview.actions.addSource': 'Add source',
        'memory.overview.actions.startChat': 'Start a conversation',
        'memory.overview.actions.connectSource': 'Connect your first source',
        'memory.overview.empty.title': 'Magi has no memories to organize yet',
        'memory.overview.empty.body': 'Add a source or start a conversation, and your memory overview will begin to take shape here.',
        'memory.overview.empty.storage': '{{value}} currently in use',
        'memory.overview.empty.sources': 'No sources connected yet',
        'memory.overview.empty.sourcesBody': 'Connect a source to see where your memories are forming.',
        'memory.sources.chat_projector': 'Chat',
        'timeline.sources.chat': 'Chat',
        'memory.stories.categories.day': 'Daily summary',
        'memory.pending.assertions.tentativeTitle': 'I found an about-you judgment: "{{value}}"',
        'memory.pending.assertions.tentativeBody': 'Is this judgment right?',
        'memory.pending.assertions.traitBody': 'Judgment type: {{trait}}',
        'memory.pending.assertions.unknownValue': 'this memory judgment',
        'memory.pending.assertions.conflictPairTitle': '"{{oldValue}}" and "{{newValue}}" do not agree',
        'memory.pending.assertions.conflictPairBody': 'The older judgment was "{{oldValue}}". Newer evidence supports "{{newValue}}" more. Confirm whether the older judgment is still accurate.',
        'memory.pending.assertions.uncertainTitle': 'I am not sure about "{{value}}"',
        'memory.pending.assertions.uncertainBody': 'The evidence is not consistent enough. Confirm whether this is accurate.',
        'memory.pending.reviews.title': 'Do you want Magi to remember “{{value}}”?',
        'memory.pending.reviews.body': 'This needs your confirmation first.',
        'memory.pending.reviews.unknownValue': 'this',
        'memory.pending.reviewEdit.title': 'Edit and confirm',
        'memory.pending.reviewEdit.description': 'Edit what you want Magi to remember.',
        'memory.pending.reviewEdit.valueLabel': 'Memory',
        'memory.pending.reviewEdit.summaryLabel': 'Note (optional)',
        'memory.pending.reviewEdit.summaryPlaceholder': 'Describe this memory',
        'memory.pending.reviewEdit.confirm': 'Confirm and save',
        'common.cancel': 'Cancel',
        'common.close': 'Close',
        'memory.pages.knowledge.readable.assertions.communication_address_preferred': 'You want me to call you "{{value}}".',
      };
      let result = translations[key] ?? '';
      if (key === 'memory.overview.metricDelta.today') {
        result = `Today +${options?.value ?? 0}`;
      } else if (!result && options && typeof options.count === 'number') {
        result = `${key}:${options.count}`;
      } else if (!result) {
        result = key;
      }
      if (options) {
        for (const [name, value] of Object.entries(options)) {
          result = result.replace(`{{${name}}}`, String(value));
        }
      }
      return result;
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
      listPendingReviews: vi.fn(),
      resolvePendingReview: vi.fn(),
      submitAssertionFeedback: vi.fn(),
      applyCorrection: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/sources', () => ({
  sourcesApi: {
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
    l0: { active_sessions: 0, total_attention_items: 0 },
    l1: { event_count: 12 },
    l2: { relation_count: 4, assertion_count: 6 },
    l3: { summary_count: 5 },
    l4: { skill_count: 1, open_circuit_breakers: 0 },
    stored_records: 28,
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
      stored_records: 9,
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
      feed_group: 'memory_update',
      summary_feed_visible: false,
      featured_rank: null,
      display_timestamp: 1710003600,
      preview_text: 'Sleep changed',
      detail_lead_text: 'Your sleep pattern looks different this week.',
    },
    {
      summary_id: 'story-trend',
      summary_type: 'insight',
      summary_category: 'trend_shift',
      title: 'Trend observed',
      content: 'Sustained interest: Codex and DeepSeek.',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003550,
      review_state: 'pending_confirmation',
      insight_key: 'trend:tools',
      insight_metadata: {},
      evidence_event_count: 6,
      feed_group: 'observations',
      summary_feed_visible: true,
      featured_rank: null,
      display_timestamp: 1710003600,
      preview_text: 'Trend observed',
      detail_lead_text: 'Sustained interest: Codex and DeepSeek.',
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
      feed_group: 'periodic',
      summary_feed_visible: true,
      featured_rank: null,
      display_timestamp: 1710003600,
      preview_text: 'A normal chat projector day.',
      detail_lead_text: '',
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
      feed_group: 'periodic',
      summary_feed_visible: true,
      featured_rank: null,
      display_timestamp: 1710003400,
      preview_text: 'Yesterday copy',
      detail_lead_text: 'A normal chat projector day.',
    },
  ],
  total: 2,
  limit: 12,
  offset: 0,
  stats: {
    highlights: 1,
    periodic: 2,
    observations: 1,
    tasks: 0,
  },
};

const SVG_ICON = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=';

const sourcePayload = {
  sources: [
    {
      source_name: 'chrome-history',
      plugin_id: 'chrome-history',
      contribution_id: 'chrome-history',
      display_name: 'Chrome History',
      display_name_translated: 'Chrome History',
      icon: SVG_ICON,
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

const renderOverview = () => render(
  <MemoryRouter>
    <MemoryOverviewPage />
  </MemoryRouter>,
);

describe('MemoryOverviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(memoryApi.getDashboard).mockResolvedValue(dashboardPayload as any);
    vi.mocked(memoryApi.listPendingReviews).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(memoryApi.resolvePendingReview).mockResolvedValue({
      review_id: 'review-1',
      status: 'confirmed',
      version: 2,
      assertion_id: 'assert-review-1',
    });
    vi.mocked(sourcesApi.getStatus).mockResolvedValue(sourcePayload as any);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(storyPayload as any);
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue(dashboardPayload.pending_assertions.items[0] as any);
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction-1',
        correction_kind: 'record_error',
        created_at: 1710000001,
        state: 'active',
      },
      current_claim: null,
      derivation_state: 'completed',
      created: true,
    });
    vi.mocked(memoryStoriesApi.review).mockResolvedValue({
      ok: true,
      summary_id: 'story-1',
      review_state: 'confirmed',
    });
  });

  it('keeps semantic event totals separate from source runtime status and plugin identity', () => {
    const source: SourceStatusItem = {
      ...sourcePayload.sources[0],
      source_name: 'browser_history',
      contribution_id: 'chromium.history',
      plugin_id: 'chromium',
      connection_id: 'browser-work',
      connection_display_name: 'Work',
      connection_revision: 2,
      last_result_count: 3,
      last_sync_at: 1710004000,
    };
    const rows = buildSourceRows([
      { source: 'browser_history', event_count: 17, avg_importance: 0.5, first_event_at: 1710001000, last_event_at: 1710003000 },
      { source: 'offline_notes', event_count: 5, avg_importance: 0.4, first_event_at: 1710001000, last_event_at: 1710002000 },
    ], { sources: [source] });

    expect(rows).toMatchObject([
      {
        key: 'browser_history',
        label: 'Chrome History',
        pluginId: 'chromium',
        eventCount: 17,
        lastResultCount: 3,
        lastEventAt: 1710003000,
        lastSyncAt: 1710004000,
        enabled: true,
      },
      {
        key: 'offline_notes',
        pluginId: null,
        eventCount: 5,
        lastResultCount: null,
        lastEventAt: 1710002000,
        lastSyncAt: null,
        enabled: null,
      },
    ]);
  });

  it('renders the compact summary, source coverage, pending review, and recent memory', async () => {
    renderOverview();

    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByTestId('memory-theme-root')).toHaveClass('px-4', 'py-4');
    expect(screen.getByTestId('memory-theme-root')).not.toHaveClass('px-6', 'py-6');
    expect(await screen.findByTestId('memory-overview-summary')).toBeInTheDocument();
    expect(await screen.findByText('Source records')).toBeInTheDocument();
    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(screen.getByText('Today +4')).toBeInTheDocument();
    expect(screen.getByText('About you')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('Today +3')).toBeInTheDocument();
    expect(screen.getByText('Reviews & summaries')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Today +2')).toBeInTheDocument();
    expect(screen.getByText('Storage')).toBeInTheDocument();
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();
    expect(screen.queryByText('Current')).not.toBeInTheDocument();
    expect(screen.getByText('Source')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getAllByText('Stored').length).toBeGreaterThan(0);
    expect(screen.getByText('Sync')).toBeInTheDocument();
    expect(screen.getByText('memory.overview.processingBacklog:5')).toBeInTheDocument();
    expect(screen.getByText('Chrome History')).toBeInTheDocument();
    expect(screen.getByTestId('plugin-icon-asset')).toHaveAttribute('src', SVG_ICON);
    expect(screen.getAllByText('Normal').length).toBeGreaterThan(0);
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.queryByText('Screen Time')).not.toBeInTheDocument();
    expect(screen.queryByText('Safari History')).not.toBeInTheDocument();
    expect(screen.queryByText('chat_projector')).not.toBeInTheDocument();
    expect(screen.getByText('I found an about-you judgment: "Python"')).toBeInTheDocument();
    expect(screen.getByText('Is this judgment right?')).toBeInTheDocument();
    expect(screen.queryByText('favorite_language')).not.toBeInTheDocument();
    expect(screen.getByText('Sleep changed')).toBeInTheDocument();
    expect(screen.queryByText('Trend observed')).not.toBeInTheDocument();
    expect(screen.queryByText('Sustained interest: Codex and DeepSeek.')).not.toBeInTheDocument();
    expect(screen.getByText('Latest summaries')).toBeInTheDocument();
    expect(screen.getByText('Daily summary')).toBeInTheDocument();
    expect(screen.getAllByText('A normal Chat day.')).toHaveLength(1);
    expect(screen.queryByText(/chat projector/i)).not.toBeInTheDocument();
    expect(memoryApi.getDashboard).toHaveBeenCalledWith({ pending_limit: 8 });
    expect(memoryApi.listPendingReviews).toHaveBeenCalledWith(8);
    expect(sourcesApi.getStatus).toHaveBeenCalled();
    expect(memoryStoriesApi.list).toHaveBeenCalledWith({ limit: 12, offset: 0, surface: 'all' });
  });

  it('shows one guided starting point when no memory data exists', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      ...dashboardPayload,
      statistics: {
        ...dashboardPayload.statistics,
        l1: { event_count: 0 },
        l2: { relation_count: 0, assertion_count: 0 },
        l3: { summary_count: 0 },
        stored_records: 0,
        disk_usage_bytes: 1_363_149,
        attention: { pending_assertions: 0, open_circuit_breakers: 0 },
      },
      source_counts: [],
      attention: { pending_assertions: 0, open_circuit_breakers: 0 },
      pending_assertions: { items: [], total: 0, limit: 8, offset: 0 },
      deltas: {
        today: {
          stored_records: 0,
          l1_events: 0,
          l2_assertions: 0,
          l3_summaries: 0,
          disk_usage_bytes: null,
        },
      },
    } as any);
    vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [] } as any);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      ...storyPayload,
      items: [],
      total: 0,
    } as any);

    renderOverview();

    expect(await screen.findByRole('heading', { name: 'Magi has no memories to organize yet' })).toBeInTheDocument();
    expect(screen.getByText('Add a source or start a conversation, and your memory overview will begin to take shape here.')).toBeInTheDocument();
    expect(screen.getByText('1.3 MB currently in use')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Add source' })).toHaveAttribute('href', '/memory/sources');
    expect(screen.getByRole('link', { name: 'Start a conversation' })).toHaveAttribute('href', '/chat');
    expect(screen.queryByTestId('memory-overview-summary')).not.toBeInTheDocument();
    expect(screen.queryByText('Source coverage')).not.toBeInTheDocument();
    expect(screen.queryByText('Latest summaries')).not.toBeInTheDocument();
  });

  it('offers a source action without showing an empty summaries section', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      ...dashboardPayload,
      statistics: {
        ...dashboardPayload.statistics,
        stored_records: 1,
      },
      source_counts: [],
      attention: { pending_assertions: 0, open_circuit_breakers: 0 },
      pending_assertions: { items: [], total: 0, limit: 8, offset: 0 },
    } as any);
    vi.mocked(sourcesApi.getStatus).mockResolvedValue({ sources: [] } as any);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      ...storyPayload,
      items: [],
      total: 0,
    } as any);

    renderOverview();

    expect(await screen.findByTestId('memory-overview-summary')).toBeInTheDocument();
    expect(screen.getByText('Source coverage')).toBeInTheDocument();
    expect(screen.getByText('No sources connected yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Connect your first source' })).toHaveAttribute('href', '/memory/sources');
    expect(screen.queryByText('Latest summaries')).not.toBeInTheDocument();
  });

  it('uses the same readable wording for pending address assertions as the review page', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      ...dashboardPayload,
      pending_assertions: {
        items: [
          {
            assertion_id: 'assert-address',
            entity_id: 'user:self',
            entity_type: 'user',
            trait_family: 'communication_profile',
            trait_name: 'communication.address.preferred',
            trait_value: '子涵',
            confidence_score: 0.52,
            evidence_events: ['evt-1'],
            validation_state: 'tentative',
            volatility_index: 0.2,
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
    } as any);

    renderOverview();

    expect(await screen.findByText('You want me to call you "子涵".')).toBeInTheDocument();
    expect(screen.getByText('Is this judgment right?')).toBeInTheDocument();
    expect(screen.queryByText('communication.address.preferred')).not.toBeInTheDocument();
    expect(screen.queryByText('I think you may care about "子涵"')).not.toBeInTheDocument();
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

    renderOverview();

    expect(await screen.findByText('Latest summaries')).toBeInTheDocument();
    expect(screen.queryByText('Pending review')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.overview.empty.pending')).not.toBeInTheDocument();
  });

  it('routes pending item actions to their owning memory APIs', async () => {
    const user = userEvent.setup();
    renderOverview();

    await screen.findByText('I found an about-you judgment: "Python"');
    await user.click(screen.getByRole('button', { name: 'Confirm assertion' }));

    expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');

    await waitFor(() => {
      expect(screen.queryByText('favorite_language')).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Confirm memory update' }));

    expect(memoryStoriesApi.review).toHaveBeenCalledWith('story-1', { review_state: 'confirmed' });
  });

  it('includes pre-materialization reviews in the overview decision list', async () => {
    vi.mocked(memoryApi.listPendingReviews).mockResolvedValue({
      items: [
        {
          review_id: 'review-1',
          subject_id: 'user:self',
          kind: 'goal_currentness',
          slot_key: 'goal-slot:seaside',
          value_fingerprint: 'goal-value:seaside',
          semantic_lineage_key: 'goal-lineage:seaside',
          claim_ids: ['claim-1'],
          reason_code: 'goal_ambiguous_time',
          proposed: {
            trait_value: 'Visit the seaside in autumn',
            natural_summary: 'The year is still unclear.',
          },
          route_contract_version: 5,
          evidence_rule_version: 2,
          source_generation: 0,
          status: 'pending',
          version: 1,
          created_at: 1710000000,
          updated_at: 1710000100,
        },
      ],
      total: 1,
    });
    const user = userEvent.setup();
    renderOverview();

    expect(await screen.findByText('Do you want Magi to remember “Visit the seaside in autumn”?')).toBeInTheDocument();
    expect(screen.getByText('Memory to confirm')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm this memory' }));

    expect(memoryApi.resolvePendingReview).toHaveBeenCalledWith('review-1', {
      action: 'confirm',
      expected_version: 1,
    });
  });

  it('opens governed correction instead of rejecting an assertion through feedback', async () => {
    const user = userEvent.setup();
    renderOverview();

    await screen.findByText('I found an about-you judgment: "Python"');
    await user.click(screen.getByRole('button', { name: 'Reject assertion' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('memory.correction.title')).toBeInTheDocument();
    expect(memoryApi.submitAssertionFeedback).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'memory.correction.removeSubmit' }));
    await waitFor(() => {
      expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
        target: { kind: 'assertion', id: 'assert-1' },
        correction_kind: 'record_error',
      }));
    });
    expect(vi.mocked(memoryApi.applyCorrection).mock.calls[0][0]).not.toHaveProperty('replacement');
  });
});
