import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TimelinePage } from '@/pages/Timeline';
import { timelineApi } from '@/api/modules/timeline';
import { memoryApi } from '@/api/modules/memory';

let mockedLanguage = 'en';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      if (params?.count !== undefined) {
        return `${key}:${params.count}`;
      }
      return key;
    },
    i18n: {
      language: mockedLanguage,
      resolvedLanguage: mockedLanguage,
    },
  }),
}));

vi.mock('@/api/modules/timeline', () => ({
  timelineApi: {
    getViewport: vi.fn(),
    getContext: vi.fn(),
  },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    submitAssertionFeedback: vi.fn(),
    correctAssertion: vi.fn(),
    annotateEpisode: vi.fn(),
    forgetEpisode: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

const localTimestamp = (year: number, monthIndex: number, day: number, hour: number, minute = 0): number =>
  Math.floor(new Date(year, monthIndex, day, hour, minute).getTime() / 1000);

const addMinutes = (timestamp: number, minutes: number): number => timestamp + minutes * 60;

const currentPreviousMonthStart = (): number => {
  const now = new Date();
  return localTimestamp(now.getFullYear(), now.getMonth() - 1, 1, 0);
};

const currentMonthStart = (): number => {
  const now = new Date();
  return localTimestamp(now.getFullYear(), now.getMonth(), 1, 0);
};

const makeOverview = (title: string, summary: string) => ({
  title,
  summary,
  key_takeaways: ['Backend takeaway'],
  confidence: 0.8,
});

const STATE_SUMMARY = {
  mood_label: 'Focused',
  stress_label: 'Moderate stress',
  engagement_label: 'High engagement',
  mood_value: 0.3,
  stress_value: 0.6,
  engagement_value: 0.8,
  notable_changes: [
    {
      label: 'State shift',
      summary: 'Stress rose around midday.',
      timestamp: 1710003600,
      anchor: { anchor_type: 'state_marker', anchor_id: 'marker-1' },
    },
  ],
};

const MONTH_VIEWPORT = {
  viewport: {
    scale: 'month',
    start: 1710000000,
    end: 1712592000,
    focus: 'self',
    query: null,
    timezone: null,
    locale: 'en',
  },
  summary: {
    cluster_count: 0,
    event_count: 8,
    dominant_modes: ['deep_work'],
  },
  overview: makeOverview('Backend month overview', 'Backend month summary.'),
  state_summary: STATE_SUMMARY,
  state_bands: [
    {
      band_id: 'band-1',
      time_start: 1710000000,
      time_end: 1712592000,
      valence: 0.3,
      stress_level: 0.6,
      engagement: 0.8,
      confidence: 0.7,
      label: 'focused',
      source_summary_ids: ['summary-1'],
      source_assertion_ids: ['assertion-1'],
    },
  ],
  state_markers: [],
  source_mix: [
    {
      source_type: 'manual_journal',
      label: 'Manual journal',
      event_count: 5,
      duration_seconds: 3600,
    },
    {
      source_type: 'chat',
      label: 'Chat',
      event_count: 3,
      duration_seconds: 1200,
    },
  ],
  theme_cards: [
    {
      theme_id: 'reflection:reflection-1',
      title: 'March reflection',
      summary: 'A steady month of focused work.',
      source_types: ['manual_journal'],
      event_count: 1,
      anchor: {
        anchor_type: 'event',
        anchor_id: 'evt-1',
        representative_event_ids: ['evt-1'],
        time_start: 1710000000,
        time_end: 1712592000,
      },
    },
  ],
  clusters: [],
  reflections: [
    {
      reflection_id: 'reflection-1',
      time_start: 1710000000,
      time_end: 1712592000,
      title: 'March reflection',
      summary: 'A steady month of focused work.',
      key_topics: ['work', 'recovery'],
      key_entities: [{ entity_id: 'project:magi' }],
      sentiment_summary: { tone: 'steady' },
      change_and_pattern: { patterns: ['late-night work'] },
      source_summary_ids: ['summary-1'],
      source_event_ids: ['evt-1'],
    },
  ],
  raw_events: [],
};

const DAY_VIEWPORT = {
  viewport: {
    scale: 'day',
    start: localTimestamp(2024, 2, 11, 0),
    end: localTimestamp(2024, 2, 12, 0),
    focus: 'self',
    query: null,
    timezone: null,
    locale: 'en',
  },
  summary: {
    cluster_count: 1,
    event_count: 3,
    dominant_modes: ['deep_work'],
  },
  overview: makeOverview('Backend day overview', 'Backend day summary.'),
  state_summary: STATE_SUMMARY,
  state_bands: MONTH_VIEWPORT.state_bands,
  state_markers: [
    {
      marker_id: 'marker-1',
      timestamp: 1710003600,
      kind: 'shift',
      label: 'State shift',
      summary: 'Stress rose around midday.',
      source_band_ids: ['band-1'],
      source_summary_ids: ['summary-1'],
    },
  ],
  source_mix: [],
  theme_cards: [],
  clusters: [
    {
      block_id: 'cluster-1',
      time_start: localTimestamp(2024, 2, 11, 9),
      time_end: localTimestamp(2024, 2, 11, 11),
      duration_seconds: 7200,
      label: 'Deep Work',
      summary: 'A long focused stretch across coding and note-taking.',
      dominant_mode: 'deep_work',
      source_types: ['chat', 'manual_journal'],
      event_count: 3,
      representative_event_ids: ['evt-1', 'evt-2'],
      keywords: ['coding', 'notes'],
      media_refs: [],
      state_snapshot: {
        valence: 0.32,
        stress_level: 0.61,
        engagement: 0.83,
      },
    },
    {
      block_id: 'cluster-2',
      time_start: localTimestamp(2024, 2, 11, 14),
      time_end: localTimestamp(2024, 2, 11, 15),
      duration_seconds: 3600,
      label: 'Review Pass',
      summary: 'Reviewed timeline implementation notes and follow-up tasks.',
      dominant_mode: 'terminal_history',
      source_types: ['terminal_history'],
      event_count: 1,
      representative_event_ids: ['evt-3'],
      keywords: ['review'],
      media_refs: [],
    },
  ],
  reflections: [],
  raw_events: [],
};

const WEEK_VIEWPORT = {
  viewport: {
    scale: 'week',
    start: localTimestamp(2024, 2, 10, 0),
    end: localTimestamp(2024, 2, 17, 0),
    focus: 'self',
    query: null,
    timezone: null,
  },
  summary: {
    cluster_count: 2,
    event_count: 3,
    dominant_modes: ['deep_work'],
  },
  overview: makeOverview('Backend week overview', 'Backend week summary.'),
  state_summary: STATE_SUMMARY,
  state_bands: MONTH_VIEWPORT.state_bands,
  state_markers: [],
  source_mix: [],
  theme_cards: [],
  clusters: [
    {
      block_id: 'episode:ep-week-1',
      episode_id: 'ep-week-1',
      time_start: localTimestamp(2024, 2, 10, 9),
      time_end: addMinutes(localTimestamp(2024, 2, 10, 9), 90),
      duration_seconds: 5400,
      label: 'Week Planning',
      summary: 'Mapped the timeline review surface milestones.',
      dominant_mode: 'manual_journal',
      source_types: ['manual_journal'],
      event_count: 2,
      representative_event_ids: ['evt-4'],
      keywords: ['planning'],
      media_refs: [],
      user_label: null,
      user_note: null,
      user_pinned: false,
    },
    {
      block_id: 'week-cluster-2',
      time_start: localTimestamp(2024, 2, 12, 15),
      time_end: localTimestamp(2024, 2, 12, 16),
      duration_seconds: 3600,
      label: 'Implementation Review',
      summary: 'Checked the evidence drawer behavior.',
      dominant_mode: 'chat',
      source_types: ['chat'],
      event_count: 1,
      representative_event_ids: ['evt-5'],
      keywords: ['evidence'],
      media_refs: [],
    },
  ],
  reflections: [],
  raw_events: [],
};

const HOUR_VIEWPORT = {
  viewport: {
    scale: 'hour',
    start: 1710000000,
    end: 1710003600,
    focus: 'self',
    query: null,
    timezone: null,
  },
  summary: {
    cluster_count: 0,
    event_count: 2,
    dominant_modes: [],
  },
  overview: makeOverview('Backend hour overview', 'Backend hour summary.'),
  state_summary: STATE_SUMMARY,
  state_bands: MONTH_VIEWPORT.state_bands,
  state_markers: [],
  source_mix: [],
  theme_cards: [],
  clusters: [],
  reflections: [],
  raw_events: [
    {
      event_id: 'evt-1',
      timestamp: 1710000300,
      title: 'Opened design note',
      summary: 'Reviewing implementation notes.',
      source_type: 'manual_journal',
    },
  ],
};

const EMPTY_VIEWPORT = {
  viewport: {
    scale: 'month',
    start: 1710000000,
    end: 1712592000,
    focus: 'self',
    query: null,
    timezone: null,
  },
  summary: {
    cluster_count: 0,
    event_count: 0,
    dominant_modes: [],
  },
  overview: makeOverview('Empty overview', ''),
  state_summary: {
    mood_label: 'Unknown',
    stress_label: 'Unknown',
    engagement_label: 'Unknown',
    notable_changes: [],
  },
  state_bands: [],
  state_markers: [],
  source_mix: [],
  theme_cards: [],
  clusters: [],
  reflections: [],
  raw_events: [],
};

const CONTEXT_BUNDLE = {
  anchor: {
    anchor_id: 'cluster-1',
    anchor_type: 'cluster',
    title: 'Deep Work',
    summary: 'A long focused stretch across coding and note-taking.',
  },
  l1_events: [{ event_id: 'evt-1', title: 'Opened design note', summary: 'Reviewing implementation notes.', source_type: 'manual_journal' }],
  l2_state_evidence: [{ assertion_id: 'assertion-1', trait_name: 'mood', trait_value: 'focused', user_feedback: null }],
  l3_reflections: [{ summary_id: 'summary-1', content: 'Focus remained high despite rising stress.' }],
  l4_related_procedures: [{ skill_id: 'skill-1', skill_name: 'Deep work loop' }],
  chat_excerpts: [{ event_id: 'evt-2', content: "Let's restructure the timeline around semantic zoom." }],
  runtime_trace: [],
};

describe('timeline page', () => {
  beforeEach(() => {
    mockedLanguage = 'en';
    vi.clearAllMocks();
    vi.mocked(timelineApi.getViewport).mockImplementation(async ({ scale }) => {
      if (scale === 'week') {
        return WEEK_VIEWPORT as any;
      }
      if (scale === 'day') {
        return DAY_VIEWPORT as any;
      }
      if (scale === 'hour') {
        return HOUR_VIEWPORT as any;
      }
      return MONTH_VIEWPORT as any;
    });
    vi.mocked(timelineApi.getContext).mockResolvedValue(CONTEXT_BUNDLE as any);
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue({
      assertion_id: 'assertion-1',
      entity_id: 'user:u1',
      entity_type: 'user',
      trait_name: 'mood',
      trait_value: 'focused',
      confidence_score: 0.95,
      evidence_events: ['evt-1'],
      validation_state: 'stable',
      volatility_index: 0.1,
      source_domain: 'timeline',
      inference_depth: 'derived',
      first_inferred_at: 1710000000,
      last_validated_at: 1710000000,
      user_feedback: 'confirmed',
      user_feedback_at: 1710001000,
    });
    vi.mocked(memoryApi.correctAssertion).mockResolvedValue({
      assertion_id: 'assertion-2',
      entity_id: 'user:u1',
      entity_type: 'user',
      trait_name: 'mood',
      trait_value: 'calm',
      confidence_score: 0.95,
      evidence_events: ['evt-1'],
      validation_state: 'stable',
      volatility_index: 0.1,
      source_domain: 'user_correction',
      inference_depth: 'explicit',
      first_inferred_at: 1710000000,
      last_validated_at: 1710001000,
      user_feedback: 'confirmed',
      user_feedback_at: 1710001000,
    });
    vi.mocked(memoryApi.annotateEpisode).mockResolvedValue({
      episode_id: 'ep-week-1',
      episode_type: 'activity',
      status: 'user_pinned',
      time_start: localTimestamp(2024, 2, 10, 9),
      time_end: addMinutes(localTimestamp(2024, 2, 10, 9), 90),
      label: 'Week Planning',
      summary: 'Mapped the timeline review surface milestones.',
      dominant_mode: 'manual_journal',
      source_event_count: 2,
      user_label: 'Pinned Planning',
      user_note: 'Keep this in review.',
      user_pinned: true,
    });
    vi.mocked(memoryApi.forgetEpisode).mockResolvedValue({
      episode_id: 'ep-week-1',
      event_ids: [],
      l1_events_deleted: 0,
    });
  });

  it('loads the month viewport first and renders reflection windows', async () => {
    render(<TimelinePage />);

    expect(await screen.findByText('Backend month overview')).toBeInTheDocument();
    expect(screen.getByText('Backend month summary.')).toBeInTheDocument();
    expect(screen.getByText('Backend takeaway')).toBeInTheDocument();
    expect(await screen.findByText('March reflection')).toBeInTheDocument();
    expect(screen.getByText('A steady month of focused work.')).toBeInTheDocument();
    expect(screen.getByText('Focused')).toBeInTheDocument();
    expect(screen.getAllByText('timeline.sources.manual_journal').length).toBeGreaterThan(0);
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(timelineApi.getViewport).toHaveBeenCalledWith(
      expect.objectContaining({
        scale: 'month',
        start: currentPreviousMonthStart(),
        end: currentMonthStart(),
        locale: 'en',
      })
    );
  });

  it('lets users jump to a specific month period', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await screen.findByText('Backend month overview');
    await user.click(screen.getByRole('button', { name: 'timeline.period.label' }));
    fireEvent.change(screen.getByLabelText('timeline.period.jump'), { target: { value: '2024-02' } });
    await user.click(screen.getByRole('button', { name: 'timeline.period.apply' }));

    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({
          scale: 'month',
          start: localTimestamp(2024, 1, 1, 0),
          end: localTimestamp(2024, 2, 1, 0),
        }),
      ),
    );
  });

  it('reloads the viewport when the app language changes', async () => {
    const { rerender } = render(<TimelinePage />);

    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({ locale: 'en' }),
      ),
    );

    mockedLanguage = 'zh-CN';
    rerender(<TimelinePage />);

    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({ locale: 'zh-CN' }),
      ),
    );
  });

  it('opens stable evidence anchors for month theme cards', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: /March reflection/ }));

    await waitFor(() => expect(timelineApi.getContext).toHaveBeenCalledWith('evt-1'));
  });

  it('switches semantic units when the scale changes', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.week' }));

    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({
          scale: 'week',
        })
      )
    );
    expect(await screen.findByText('Week Planning')).toBeInTheDocument();
    expect(screen.getByText('Implementation Review')).toBeInTheDocument();
    expect(screen.getByText('timeline.cluster.groupSummary:2')).toBeInTheDocument();
    expect(screen.getByText('timeline.cluster.groupSummary:1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'timeline.scale.day' }));

    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({
          scale: 'day',
        })
      )
    );
    expect(await screen.findByText('Deep Work')).toBeInTheDocument();
    expect(screen.getByText('Review Pass')).toBeInTheDocument();
    expect(screen.getByText('timeline.day.segments.morning')).toBeInTheDocument();
    expect(screen.getByText('timeline.day.segments.afternoon')).toBeInTheDocument();
    expect(screen.getByText('#coding')).toBeInTheDocument();
    expect(screen.getByText('#notes')).toBeInTheDocument();
    expect(screen.getByText('timeline.sources.chat')).toBeInTheDocument();
    expect(screen.getByText('timeline.sources.manual_journal')).toBeInTheDocument();
    expect(screen.queryByText('March reflection')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'timeline.scale.hour' }));
    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({
          scale: 'hour',
        })
      )
    );
    expect(await screen.findByText('Opened design note')).toBeInTheDocument();
    expect(screen.queryByText('Deep Work')).not.toBeInTheDocument();
  });

  it('opens stable evidence anchors for episode clusters', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.week' }));
    await user.click(await screen.findByRole('button', { name: /Week Planning/ }));

    await waitFor(() => expect(timelineApi.getContext).toHaveBeenCalledWith('episode:ep-week-1'));
  });

  it('pins and annotates episode-backed review periods', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.week' }));
    await user.click(await screen.findByRole('button', { name: 'timeline.episode.pin' }));

    await waitFor(() => expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('ep-week-1', { user_pinned: true }));

    await user.click(await screen.findByRole('button', { name: 'timeline.episode.edit' }));
    await user.clear(await screen.findByLabelText('timeline.episode.label'));
    await user.type(screen.getByLabelText('timeline.episode.label'), 'Pinned Planning');
    await user.type(screen.getByLabelText('timeline.episode.note'), 'Keep this in review.');
    await user.click(screen.getByRole('button', { name: 'timeline.episode.save' }));

    await waitFor(() => expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('ep-week-1', {
      user_label: 'Pinned Planning',
      user_note: 'Keep this in review.',
    }));
  });

  it('hides episode-backed review periods without deleting source events', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.week' }));
    await user.click(await screen.findByRole('button', { name: 'timeline.episode.hide' }));

    await waitFor(() => expect(memoryApi.forgetEpisode).toHaveBeenCalledWith('ep-week-1', false));
  });

  it('opens the context drawer when a cluster is selected', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.day' }));
    await user.click(await screen.findByRole('button', { name: /Deep Work/ }));

    await waitFor(() => expect(timelineApi.getContext).toHaveBeenCalledWith('evt-1'));
    const sourceEvidence = await screen.findByText('timeline.drawer.sourceEvidence');
    const derivedEvidence = screen.getByText('timeline.drawer.derivedEvidence');
    const reflections = screen.getByText('timeline.drawer.reflections');
    expect(sourceEvidence.compareDocumentPosition(derivedEvidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(derivedEvidence.compareDocumentPosition(reflections) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('Opened design note')).toBeInTheDocument();
    expect(screen.getByText('mood')).toBeInTheDocument();
    expect(screen.getByText('timeline.drawer.relatedChat')).toBeInTheDocument();
    expect(await screen.findByText('Focus remained high despite rising stress.')).toBeInTheDocument();
    expect(screen.getByText('Deep work loop')).toBeInTheDocument();
  });

  it('submits assertion feedback from derived timeline evidence', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.day' }));
    await user.click(await screen.findByRole('button', { name: /Deep Work/ }));
    await user.click(await screen.findByRole('button', { name: 'timeline.feedback.confirm' }));

    await waitFor(() => expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assertion-1', 'confirmed'));
    expect(await screen.findByText('timeline.feedback.status.confirmed')).toBeInTheDocument();
  });

  it('submits assertion corrections from derived timeline evidence', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.day' }));
    await user.click(await screen.findByRole('button', { name: /Deep Work/ }));
    await user.click(await screen.findByRole('button', { name: 'timeline.feedback.correct' }));
    await user.clear(await screen.findByLabelText('timeline.feedback.correctValue'));
    await user.type(screen.getByLabelText('timeline.feedback.correctValue'), 'calm');
    await user.click(screen.getByRole('button', { name: 'timeline.feedback.saveCorrection' }));

    await waitFor(() => expect(memoryApi.correctAssertion).toHaveBeenCalledWith('assertion-1', 'calm'));
    expect(await screen.findByText('calm')).toBeInTheDocument();
  });

  it('renders an empty state when the viewport has no reviewable content', async () => {
    vi.mocked(timelineApi.getViewport).mockResolvedValueOnce(EMPTY_VIEWPORT as any);

    render(<TimelinePage />);

    expect(await screen.findByText('timeline.feed.emptyTitle')).toBeInTheDocument();
    expect(screen.getByText('timeline.feed.emptyBody')).toBeInTheDocument();
  });
});
