import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TimelinePage } from '@/pages/Timeline';
import { timelineApi } from '@/api/modules/timeline';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      if (params?.count !== undefined) {
        return `${key}:${params.count}`;
      }
      return key;
    },
    i18n: {
      language: 'en',
    },
  }),
}));

vi.mock('@/api/modules/timeline', () => ({
  timelineApi: {
    getViewport: vi.fn(),
    getContext: vi.fn(),
  },
}));

const MONTH_VIEWPORT = {
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
    event_count: 8,
    dominant_modes: ['deep_work'],
  },
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
    start: 1710000000,
    end: 1710086400,
    focus: 'self',
    query: null,
    timezone: null,
  },
  summary: {
    cluster_count: 1,
    event_count: 3,
    dominant_modes: ['deep_work'],
  },
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
  clusters: [
    {
      block_id: 'cluster-1',
      time_start: 1710000000,
      time_end: 1710007200,
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
  state_bands: MONTH_VIEWPORT.state_bands,
  state_markers: [],
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
  state_bands: [],
  state_markers: [],
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
  l2_state_evidence: [{ assertion_id: 'assertion-1', trait_name: 'mood', trait_value: 'focused' }],
  l3_reflections: [{ summary_id: 'summary-1', content: 'Focus remained high despite rising stress.' }],
  l4_related_procedures: [{ skill_id: 'skill-1', skill_name: 'Deep work loop' }],
  chat_excerpts: [{ event_id: 'evt-2', content: "Let's restructure the timeline around semantic zoom." }],
  runtime_trace: [],
};

describe('timeline page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timelineApi.getViewport).mockImplementation(async ({ scale }) => {
      if (scale === 'day') {
        return DAY_VIEWPORT as any;
      }
      if (scale === 'hour') {
        return HOUR_VIEWPORT as any;
      }
      return MONTH_VIEWPORT as any;
    });
    vi.mocked(timelineApi.getContext).mockResolvedValue(CONTEXT_BUNDLE as any);
  });

  it('loads the month viewport first and renders reflection windows', async () => {
    render(<TimelinePage />);

    expect(await screen.findByText('March reflection')).toBeInTheDocument();
    expect(screen.getByText('A steady month of focused work.')).toBeInTheDocument();
    expect(screen.getAllByText('focused').length).toBeGreaterThan(0);
    expect(screen.getByText('work')).toBeInTheDocument();
    expect(screen.getByText('recovery')).toBeInTheDocument();
    expect(timelineApi.getViewport).toHaveBeenCalledWith(
      expect.objectContaining({
        scale: 'month',
      })
    );
  });

  it('switches semantic units when the scale changes', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.day' }));

    await waitFor(() =>
      expect(timelineApi.getViewport).toHaveBeenLastCalledWith(
        expect.objectContaining({
          scale: 'day',
        })
      )
    );
    expect(await screen.findByText('Deep Work')).toBeInTheDocument();
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

  it('opens the context drawer when a cluster is selected', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.scale.day' }));
    await user.click(await screen.findByRole('button', { name: /Deep Work/ }));

    await waitFor(() => expect(timelineApi.getContext).toHaveBeenCalledWith('cluster-1'));
    expect(await screen.findByText('timeline.drawer.sourceEvidence')).toBeInTheDocument();
    expect(screen.getByText('Opened design note')).toBeInTheDocument();
    expect(screen.getByText('timeline.drawer.derivedEvidence')).toBeInTheDocument();
    expect(screen.getByText('mood')).toBeInTheDocument();
    expect(screen.getByText('timeline.drawer.relatedChat')).toBeInTheDocument();
    expect(await screen.findByText('Focus remained high despite rising stress.')).toBeInTheDocument();
    expect(screen.getByText('Deep work loop')).toBeInTheDocument();
  });

  it('renders an empty state when the viewport has no reviewable content', async () => {
    vi.mocked(timelineApi.getViewport).mockResolvedValueOnce(EMPTY_VIEWPORT as any);

    render(<TimelinePage />);

    expect(await screen.findByText('timeline.feed.emptyTitle')).toBeInTheDocument();
    expect(screen.getByText('timeline.feed.emptyBody')).toBeInTheDocument();
  });
});
