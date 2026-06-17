import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryEpisodesPage } from '@/pages/memory-pages/MemoryEpisodesPage';
import { memoryApi } from '@/api/modules/memory';
import type { L2EpisodeDetail, L2EpisodeInference, L2EpisodeWithSummary } from '@/api/modules/memory';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.episodes.title': 'Experiences',
    'memory.episodes.subtitle': 'Active experiences Magi has formed from remembered events.',
    'memory.episodes.sections.list': 'Active experiences',
    'memory.episodes.sections.detail': 'Experience detail',
    'memory.episodes.sections.narrative': 'Narrative',
    'memory.episodes.sections.eventStream': 'Event stream',
    'memory.episodes.sections.inferred': 'Inferred impressions',
    'memory.episodes.sections.people': 'People',
    'memory.episodes.sections.places': 'Places',
    'memory.episodes.sections.topics': 'Topics',
    'memory.episodes.sections.userNotes': 'Your corrections',
    'memory.episodes.count': '{{count}} active',
    'memory.episodes.emptyTitle': 'No active experiences yet',
    'memory.episodes.emptyBody': 'Magi will form episodes as conversations and activity accumulate.',
    'memory.episodes.detailEmptyTitle': 'Choose an experience',
    'memory.episodes.detailEmptyBody': 'Open one from the list to inspect its events and impressions.',
    'memory.episodes.noNarrative': 'No narrative yet.',
    'memory.episodes.noSummary': 'No summary yet.',
    'memory.episodes.noEvents': 'No event memberships found.',
    'memory.episodes.noInferred': 'No inferred impressions for this episode.',
    'memory.episodes.noTags': 'None yet',
    'memory.episodes.awaitingLabel': 'Waiting for Magi to draft a title...',
    'memory.episodes.fields.label': 'Label',
    'memory.episodes.fields.note': 'Note',
    'memory.episodes.fields.pinned': 'Pinned',
    'memory.episodes.actions.open': 'Open experience',
    'memory.episodes.actions.edit': 'Edit corrections',
    'memory.episodes.actions.pin': 'Pin',
    'memory.episodes.actions.unpin': 'Unpin',
    'memory.episodes.actions.saveCorrections': 'Save corrections',
    'memory.episodes.actions.confirmImpression': 'Confirm impression',
    'memory.episodes.actions.rejectImpression': 'Reject impression',
    'memory.episodes.filters.activity': 'Activity',
    'memory.episodes.eventRole.member': 'Member',
    'memory.episodes.feedback.confirmed': 'Confirmed',
    'memory.episodes.feedback.rejected': 'Rejected',
    'memory.episodes.feedback.pending': 'Needs review',
    'common.save': 'Save',
    'common.cancel': 'Cancel',
    'common.loading': 'Loading...',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        let result = labels[key] ?? String(opts?.defaultValue ?? key);
        if (opts) {
          for (const [name, value] of Object.entries(opts)) {
            result = result.replace(`{{${name}}}`, String(value));
          }
        }
        return result;
      },
      i18n: { language: 'en' },
    }),
  };
});

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    listEpisodes: vi.fn(),
    getEpisode: vi.fn(),
    annotateEpisode: vi.fn(),
    submitAssertionFeedback: vi.fn(),
    mergeEpisodes: vi.fn(),
  },
}));

const activeEpisodes: L2EpisodeWithSummary[] = [
  {
    episode_id: 'ep-1',
    episode_type: 'activity',
    status: 'active',
    user_pinned: true,
    user_label: 'Launch week',
    user_note: 'Keep this as the product kickoff.',
    label: 'Launch cluster',
    summary: 'Magi noticed a focused launch thread.',
    slice_narrative: 'You spent the afternoon turning a vague launch idea into a concrete plan.',
    time_start: 1700000000,
    time_end: 1700100000,
    source_event_count: 3,
    primary_entity_ids: ['person:asuka'],
    primary_place_ids: ['place:studio'],
    primary_topic_keys: ['topic:launch'],
    dominant_mode: 'planning',
  },
  {
    episode_id: 'ep-2',
    episode_type: 'activity',
    status: 'active',
    user_pinned: false,
    user_label: null,
    user_note: null,
    label: 'Research loop',
    summary: 'Researching competitor onboarding.',
    slice_narrative: '',
    time_start: 1700200000,
    time_end: 1700300000,
    source_event_count: 2,
    primary_entity_ids: [],
    primary_place_ids: [],
    primary_topic_keys: ['topic:onboarding'],
    dominant_mode: 'research',
  },
];

const episodeDetail: L2EpisodeDetail = {
  ...activeEpisodes[0],
  events: [
    {
      episode_id: 'ep-1',
      event_id: 'evt-1',
      membership_role: 'member',
      membership_confidence: 0.92,
      added_at: 1700100000,
    },
    {
      episode_id: 'ep-1',
      event_id: 'evt-2',
      membership_role: 'member',
      membership_confidence: 0.8,
      added_at: 1700100300,
    },
  ],
  inferred: [
    {
      assertion_id: 'assert-1',
      entity_id: 'person:asuka',
      entity_type: 'person',
      trait_family: 'preference_profile',
      trait_name: 'work.mode',
      trait_value: 'likes structured launch planning',
      confidence_score: 0.81,
      natural_summary: 'You seem to prefer structured launch planning.',
      validation_state: 'tentative',
      user_feedback: null,
      evidence_events: ['evt-1'],
    },
  ],
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <MemoryEpisodesPage />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
    items: activeEpisodes,
    total: 2,
    limit: 100,
    offset: 0,
  } as never);
  vi.mocked(memoryApi.getEpisode).mockResolvedValue(episodeDetail);
  vi.mocked(memoryApi.annotateEpisode).mockResolvedValue(activeEpisodes[0]);
  const firstInference = episodeDetail.inferred[0] as L2EpisodeInference;
  vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue({
    ...firstInference,
    user_feedback: 'confirmed',
  } as never);
});

describe('MemoryEpisodesPage', () => {
  it('lists active episodes with default API filters and opens the first detail', async () => {
    renderPage();

    expect((await screen.findAllByText('Launch week')).length).toBeGreaterThan(0);
    expect(screen.getByText('Research loop')).toBeInTheDocument();
    expect(memoryApi.listEpisodes).toHaveBeenCalledWith({ limit: 100, offset: 0 });
    expect(memoryApi.listEpisodes).not.toHaveBeenCalledWith(expect.objectContaining({ surface: 'standout' }));
    expect(memoryApi.getEpisode).toHaveBeenCalledWith('ep-1');
  });

  it('renders narrative, event stream, inferred impressions, and people/place/topic chips', async () => {
    renderPage();

    expect(await screen.findByText('You spent the afternoon turning a vague launch idea into a concrete plan.')).toBeInTheDocument();
    expect(screen.getAllByText('Magi noticed a focused launch thread.').length).toBeGreaterThan(0);

    const events = screen.getByTestId('episode-event-stream');
    expect(within(events).getByText('evt-1')).toBeInTheDocument();
    expect(within(events).getByText('evt-2')).toBeInTheDocument();

    expect(screen.getByText('You seem to prefer structured launch planning.')).toBeInTheDocument();
    expect(screen.getAllByText('person:asuka').length).toBeGreaterThan(0);
    expect(screen.getByText('place:studio')).toBeInTheDocument();
    expect(screen.getByText('topic:launch')).toBeInTheDocument();
  });

  it('saves user label, note, and pin corrections through the episode patch API', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findAllByText('Launch week');
    await user.click(screen.getByRole('button', { name: 'Edit corrections' }));
    await user.clear(screen.getByLabelText('Label'));
    await user.type(screen.getByLabelText('Label'), 'Launch sprint');
    await user.clear(screen.getByLabelText('Note'));
    await user.type(screen.getByLabelText('Note'), 'This was more about launch prep than execution.');
    await user.click(screen.getByLabelText('Pinned'));
    await user.click(screen.getByRole('button', { name: 'Save corrections' }));

    await waitFor(() => {
      expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('ep-1', {
        user_label: 'Launch sprint',
        user_note: 'This was more about launch prep than execution.',
        user_pinned: false,
      });
    });
  });

  it('submits assertion feedback from inferred impressions', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('You seem to prefer structured launch planning.');
    await user.click(screen.getByRole('button', { name: 'Confirm impression' }));

    await waitFor(() => {
      expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');
    });
  });
});
