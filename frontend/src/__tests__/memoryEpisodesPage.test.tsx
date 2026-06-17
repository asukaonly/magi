import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryEpisodesPage } from '@/pages/memory-pages/MemoryEpisodesPage';
import { memoryApi } from '@/api/modules/memory';
import type { L2EpisodeReviewDetail, L2EpisodeWithSummary } from '@/api/modules/memory';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.episodes.title': 'Experiences',
    'memory.episodes.subtitle': 'Active experiences Magi has formed from remembered events.',
    'memory.episodes.sections.list': 'Active experiences',
    'memory.episodes.sections.detail': 'Experience detail',
    'memory.episodes.sections.recap': 'Recap',
    'memory.episodes.sections.whatHappened': 'What happened',
    'memory.episodes.sections.people': 'People',
    'memory.episodes.sections.places': 'Places',
    'memory.episodes.sections.topics': 'Topics',
    'memory.episodes.count': '{{count}} active',
    'memory.episodes.emptyTitle': 'No active experiences yet',
    'memory.episodes.emptyBody': 'Magi will form episodes as conversations and activity accumulate.',
    'memory.episodes.detailEmptyTitle': 'Choose an experience',
    'memory.episodes.detailEmptyBody': 'Open one from the list to inspect its events and impressions.',
    'memory.episodes.noRecap': 'No recap yet.',
    'memory.episodes.noEvents': 'No event memberships found.',
    'memory.episodes.noTags': 'None yet',
    'memory.episodes.awaitingLabel': 'Waiting for Magi to draft a title...',
    'memory.episodes.fields.title': 'Title',
    'memory.episodes.fields.description': 'Recap',
    'memory.episodes.fields.pinned': 'Pinned',
    'memory.episodes.actions.open': 'Open experience',
    'memory.episodes.actions.rename': 'Rename',
    'memory.episodes.actions.editDescription': 'Edit recap',
    'memory.episodes.actions.regenerateDescription': 'Regenerate recap',
    'memory.episodes.actions.addEvent': 'Add event',
    'memory.episodes.actions.removeEvent': 'Remove event',
    'memory.episodes.actions.mergeEpisode': 'Merge',
    'memory.episodes.actions.splitEpisode': 'Split',
    'memory.episodes.actions.confirmRegenerate': 'Regenerate now',
    'memory.episodes.actions.confirmImpression': 'Confirm impression',
    'memory.episodes.actions.rejectImpression': 'Reject impression',
    'memory.episodes.dialogs.renameTitle': 'Rename experience',
    'memory.episodes.dialogs.renameDescription': 'Update the title shown for this experience.',
    'memory.episodes.dialogs.editDescriptionTitle': 'Edit recap',
    'memory.episodes.dialogs.editDescriptionDescription': 'Update the recap shown on this experience.',
    'memory.episodes.dialogs.regenerateTitle': 'Replace current recap?',
    'memory.episodes.dialogs.regenerateDescription': 'Magi will draft a new recap for this experience.',
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
    regenerateEpisode: vi.fn(),
    listEpisodeEventCandidates: vi.fn(),
    addEpisodeEvents: vi.fn(),
    removeEpisodeEvents: vi.fn(),
    listEpisodeMergeCandidates: vi.fn(),
    mergeEpisodes: vi.fn(),
    previewEpisodeSplit: vi.fn(),
    splitEpisode: vi.fn(),
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
    episode_summary: {
      summary_id: 'sum-1',
      content: 'Generated Japan recap',
      label: 'Japan launch trip',
      updated_at: 1700100000,
      is_fallback: false,
    },
    display_title: 'Launch week',
    display_description: 'Keep this as the product kickoff.',
    display_source: 'user_override',
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
    episode_summary: {
      summary_id: 'sum-2',
      content: 'Generated research recap',
      label: 'Generated research loop',
      updated_at: 1700300000,
      is_fallback: false,
    },
    display_title: 'Generated research loop',
    display_description: 'Generated research recap',
    display_source: 'generated',
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

const episodeDetail: L2EpisodeReviewDetail = {
  ...activeEpisodes[0],
  user_note: null,
  display_title: 'Launch week',
  display_description: 'Generated Japan recap',
  display_source: 'generated',
  events: [
    {
      episode_id: 'ep-1',
      event_id: 'evt-1',
      membership_role: 'member',
      membership_confidence: 0.92,
      added_at: 1700100000,
      timestamp: 1700100000,
      event_type: 'UserMessage',
      source: 'chat',
      content_preview: 'Visited Kyoto station',
    },
    {
      episode_id: 'ep-1',
      event_id: 'evt-2',
      membership_role: 'member',
      membership_confidence: 0.8,
      added_at: 1700100300,
      timestamp: 1700100300,
      event_type: 'UserMessage',
      source: 'chat',
      content_preview: 'Booked the Shinkansen tickets',
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
  vi.mocked(memoryApi.regenerateEpisode).mockResolvedValue(episodeDetail);
});

describe('MemoryEpisodesPage', () => {
  it('lists active episodes with default API filters and opens the first detail', async () => {
    renderPage();

    expect((await screen.findAllByText('Launch week')).length).toBeGreaterThan(0);
    expect(screen.getByText('Generated research loop')).toBeInTheDocument();
    expect(memoryApi.listEpisodes).toHaveBeenCalledWith({ limit: 100, offset: 0 });
    expect(memoryApi.listEpisodes).not.toHaveBeenCalledWith(expect.objectContaining({ surface: 'standout' }));
    expect(memoryApi.getEpisode).toHaveBeenCalledWith('ep-1');
  });

  it('renders the Magi recap and event previews without inference feedback controls', async () => {
    renderPage();

    expect(await screen.findByText('Generated Japan recap')).toBeInTheDocument();

    const events = screen.getByTestId('episode-event-stream');
    expect(within(events).getByText('Visited Kyoto station')).toBeInTheDocument();
    expect(within(events).getByText('Booked the Shinkansen tickets')).toBeInTheDocument();

    expect(screen.queryByText('Confirm impression')).not.toBeInTheDocument();
    expect(screen.queryByText('You seem to prefer structured launch planning.')).not.toBeInTheDocument();
    expect(screen.getAllByText('person:asuka').length).toBeGreaterThan(0);
    expect(screen.getByText('place:studio')).toBeInTheDocument();
    expect(screen.getByText('topic:launch')).toBeInTheDocument();
  });

  it('renames the selected experience through the annotation API', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.annotateEpisode).mockResolvedValue({
      ...activeEpisodes[0],
      user_label: 'Launch sprint',
      display_title: 'Launch sprint',
    } as never);
    renderPage();

    await screen.findByText('Generated Japan recap');
    await user.click(screen.getByRole('button', { name: 'Rename' }));
    await user.clear(screen.getByLabelText('Title'));
    await user.type(screen.getByLabelText('Title'), 'Launch sprint');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('ep-1', {
        user_label: 'Launch sprint',
      });
    });
  });

  it('edits the selected recap through the annotation API', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.annotateEpisode).mockResolvedValue({
      ...activeEpisodes[0],
      user_note: 'This was more about launch prep than execution.',
      display_description: 'This was more about launch prep than execution.',
    } as never);
    renderPage();

    await screen.findByText('Generated Japan recap');
    await user.click(screen.getByRole('button', { name: 'Edit recap' }));
    await user.clear(screen.getByLabelText('Recap'));
    await user.type(screen.getByLabelText('Recap'), 'This was more about launch prep than execution.');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('ep-1', {
        user_note: 'This was more about launch prep than execution.',
      });
    });
  });

  it('confirms before regenerating over a user-edited recap', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.getEpisode).mockResolvedValue({
      ...episodeDetail,
      user_note: 'Manual recap',
      display_description: 'Manual recap',
      display_source: 'user_override',
    });
    vi.mocked(memoryApi.regenerateEpisode).mockResolvedValue({
      ...episodeDetail,
      display_description: 'Fresh generated recap',
      episode_summary: {
        summary_id: 'sum-new',
        content: 'Fresh generated recap',
        label: 'Fresh generated title',
        updated_at: 1700200000,
        is_fallback: false,
      },
    });
    renderPage();

    await screen.findByText('Manual recap');
    await user.click(screen.getByRole('button', { name: 'Regenerate recap' }));
    expect(screen.getByText('Replace current recap?')).toBeInTheDocument();
    expect(memoryApi.regenerateEpisode).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Regenerate now' }));

    await waitFor(() => {
      expect(memoryApi.regenerateEpisode).toHaveBeenCalledWith('ep-1');
    });
    expect((await screen.findAllByText('Fresh generated recap')).length).toBeGreaterThan(0);
  });
});
