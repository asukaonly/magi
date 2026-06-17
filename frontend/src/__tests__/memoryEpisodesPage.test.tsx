import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryEpisodesPage } from '@/pages/memory-pages/MemoryEpisodesPage';
import { memoryApi } from '@/api/modules/memory';
import type { L2ExperienceReviewDetail, L2ExperienceWithReview } from '@/api/modules/memory';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.episodes.title': 'Experiences',
    'memory.episodes.subtitle': 'Recently formed and updated experiences from remembered events.',
    'memory.episodes.sections.list': 'Recently updated experiences',
    'memory.episodes.sections.all': 'All experiences',
    'memory.episodes.sections.detail': 'Experience review',
    'memory.episodes.sections.recap': "Magi's recap",
    'memory.episodes.sections.whatHappened': 'Event trail',
    'memory.episodes.sections.sourceEpisodes': 'Source chapters',
    'memory.episodes.sections.entities': 'Entities',
    'memory.episodes.sections.places': 'Places',
    'memory.episodes.sections.topics': 'Topics',
    'memory.episodes.sections.keywords': 'Keywords',
    'memory.episodes.sortNote': 'Pinned first · Recently updated',
    'memory.episodes.searchLabel': 'Search experiences',
    'memory.episodes.searchPlaceholder': 'Search experiences, places, topics',
    'memory.episodes.filterPinned': 'Filter',
    'memory.episodes.filterPinnedActive': 'Pinned only',
    'memory.episodes.featuredLabel': 'Featured recap',
    'memory.episodes.unknownMonth': 'Undated',
    'memory.episodes.count': '{{count}} active',
    'memory.episodes.eventCount': '{{count}} events',
    'memory.episodes.episodeCount': '{{count}} source episodes',
    'memory.episodes.emptyTitle': 'No active experiences yet',
    'memory.episodes.emptyBody': 'Magi will form experiences as conversations and activity accumulate. If you already have remembered activity, run a refresh now.',
    'memory.episodes.detailEmptyTitle': 'Choose an experience',
    'memory.episodes.detailEmptyBody': 'Open one from the list to inspect its events and impressions.',
    'memory.episodes.noRecap': 'No recap yet.',
    'memory.episodes.noEvents': 'No event memberships found.',
    'memory.episodes.noSourceEpisodes': 'No source episodes found.',
    'memory.episodes.noSearchResults': 'No experiences match those filters.',
    'memory.episodes.eventPreviewUnavailable': 'Event preview unavailable',
    'memory.episodes.noTags': 'None yet',
    'memory.episodes.awaitingLabel': 'Waiting for Magi to draft a title...',
    'memory.episodes.fields.title': 'Title',
    'memory.episodes.fields.description': 'Recap',
    'memory.episodes.fields.pinned': 'Pinned',
    'memory.episodes.actions.open': 'Open experience',
    'memory.episodes.actions.rename': 'Rename',
    'memory.episodes.actions.editDescription': 'Edit recap',
    'memory.episodes.actions.regenerateDescription': 'Regenerate recap',
    'memory.episodes.actions.hide': 'Hide',
    'memory.episodes.actions.confirmRegenerate': 'Regenerate now',
    'memory.episodes.actions.confirmHide': 'Hide experience',
    'memory.episodes.actions.reconsolidate': 'Build experiences now',
    'memory.episodes.actions.reconsolidating': 'Building...',
    'memory.episodes.reconsolidateResult': '{{promoted}} promoted · {{standouts}} standout · {{summaries}} summaries',
    'memory.episodes.dialogs.renameTitle': 'Rename experience',
    'memory.episodes.dialogs.renameDescription': 'Update the title shown for this experience.',
    'memory.episodes.dialogs.editDescriptionTitle': 'Edit recap',
    'memory.episodes.dialogs.editDescriptionDescription': 'Update the recap shown on this experience.',
    'memory.episodes.dialogs.regenerateTitle': 'Replace current recap?',
    'memory.episodes.dialogs.regenerateDescription': 'Magi will draft a new recap for this experience.',
    'memory.episodes.dialogs.hideTitle': 'Hide this experience?',
    'memory.episodes.dialogs.hideDescription': 'It will leave the main experience shelf but keep the underlying memories.',
    'memory.episodes.filters.activity': 'Activity',
    'memory.episodes.eventRole.member': 'Member',
    'common.save': 'Save',
    'common.cancel': 'Cancel',
    'common.loading': 'Loading...',
    'common.saving': 'Saving...',
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
    listExperiences: vi.fn(),
    getExperience: vi.fn(),
    annotateExperience: vi.fn(),
    regenerateExperienceReview: vi.fn(),
    hideExperience: vi.fn(),
    listEpisodes: vi.fn(),
    reconsolidateEpisodes: vi.fn(),
  },
}));

const activeExperiences: L2ExperienceWithReview[] = [
  {
    experience_id: 'exp-1',
    experience_type: 'activity',
    status: 'active',
    user_pinned: true,
    user_label: 'Launch week',
    user_note: 'Keep this as the product kickoff.',
    title: 'Launch cluster',
    magi_interpretation: 'Magi noticed a focused launch thread.',
    experience_review: {
      summary_id: 'sum-1',
      content: 'Generated Japan recap',
      label: 'Japan launch trip',
      updated_at: 1700100000,
      is_fallback: false,
    },
    display_title: 'Launch week',
    display_description: 'Keep this as the product kickoff.',
    display_source: 'user_override',
    intent: 'Turn a vague launch idea into a concrete plan.',
    time_start: 1700000000,
    time_end: 1700100000,
    updated_at: 1700100000,
    source_episode_count: 2,
    source_event_count: 3,
    primary_entity_ids: ['person:asuka'],
    primary_entities: [{ id: 'person:asuka', name: 'Asuka', type: 'person' }],
    primary_place_ids: ['place:studio'],
    primary_topic_keys: ['topic:launch'],
  },
  {
    experience_id: 'exp-2',
    experience_type: 'activity',
    status: 'active',
    user_pinned: false,
    user_label: null,
    user_note: null,
    title: 'Research loop',
    magi_interpretation: 'Researching competitor onboarding.',
    experience_review: {
      summary_id: 'sum-2',
      content: 'Generated research recap',
      label: 'Generated research loop',
      updated_at: 1700300000,
      is_fallback: false,
    },
    display_title: 'Generated research loop',
    display_description: 'Generated research recap',
    display_source: 'generated',
    time_start: 1700200000,
    time_end: 1700300000,
    updated_at: 1700300000,
    source_episode_count: 1,
    source_event_count: 2,
    primary_entity_ids: [],
    primary_place_ids: [],
    primary_topic_keys: ['topic:onboarding'],
  },
  {
    experience_id: 'exp-3',
    experience_type: 'activity',
    status: 'active',
    user_pinned: false,
    user_label: 'Earlier browsing',
    user_note: null,
    title: 'Earlier browsing',
    magi_interpretation: 'A quieter earlier reading session.',
    experience_review: {
      summary_id: 'sum-3',
      content: 'Generated earlier recap',
      label: 'Earlier browsing',
      updated_at: 1700150000,
      is_fallback: false,
    },
    display_title: 'Earlier browsing',
    display_description: 'Generated earlier recap',
    display_source: 'generated',
    time_start: 1700120000,
    time_end: 1700150000,
    updated_at: 1700150000,
    source_episode_count: 1,
    source_event_count: 4,
    primary_entity_ids: [],
    primary_place_ids: [],
    primary_topic_keys: ['topic:archive'],
  },
];

const experienceDetail: L2ExperienceReviewDetail = {
  ...activeExperiences[0],
  user_note: null,
  display_title: 'Launch week',
  display_description: 'Generated Japan recap',
  display_source: 'generated',
  source_episodes: [
    {
      episode_id: 'ep-1',
      episode_type: 'activity',
      status: 'active',
      label: 'Planning thread',
      summary: 'Product launch planning.',
      time_start: 1700000000,
      time_end: 1700050000,
      source_event_count: 2,
      primary_entity_ids: [],
      primary_place_ids: [],
      primary_topic_keys: ['topic:launch'],
      membership_role: 'core',
      membership_confidence: 0.9,
      membership_added_at: 1700100000,
    },
  ],
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
  key_events: [],
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <MemoryEpisodesPage />
    </MemoryRouter>
  );

const openLaunchExperience = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole('button', { name: /Open experience: Launch week/ }));
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memoryApi.listExperiences).mockResolvedValue({
    items: [activeExperiences[1], activeExperiences[2], activeExperiences[0]],
    total: 3,
    limit: 100,
    offset: 0,
  } as never);
  vi.mocked(memoryApi.getExperience).mockResolvedValue(experienceDetail);
  vi.mocked(memoryApi.annotateExperience).mockResolvedValue(experienceDetail);
  vi.mocked(memoryApi.regenerateExperienceReview).mockResolvedValue(experienceDetail);
  vi.mocked(memoryApi.hideExperience).mockResolvedValue({
    ...experienceDetail,
    status: 'hidden',
  });
  vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
    items: [],
    total: 0,
    limit: 100,
    offset: 0,
  } as never);
  vi.mocked(memoryApi.reconsolidateEpisodes).mockResolvedValue({
    promoted: 1,
    standouts: 1,
    merged: 0,
    invalidated: 0,
    summaries_generated: 1,
    summary_errors: [],
  } as never);
});

describe('MemoryEpisodesPage', () => {
  it('lists experiences and opens the first one in the detail rail', async () => {
    renderPage();

    expect((await screen.findAllByText('Launch week')).length).toBeGreaterThan(0);
    expect(screen.getByText('Generated research loop')).toBeInTheDocument();
    expect(screen.getByText('Pinned first · Recently updated')).toBeInTheDocument();
    expect(screen.getByText('All experiences')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Build experiences now' })).toBeInTheDocument();

    const experienceButtons = screen.getAllByRole('button', { name: /Open experience:/ });
    expect(experienceButtons.map((button) => button.getAttribute('aria-label'))).toEqual([
      'Open experience: Launch week',
      'Open experience: Generated research loop',
      'Open experience: Earlier browsing',
    ]);
    expect(memoryApi.listExperiences).toHaveBeenCalledWith({ status: 'active', limit: 100, offset: 0 });
    expect(memoryApi.listEpisodes).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(memoryApi.getExperience).toHaveBeenCalledWith('exp-1');
    });
    expect(await screen.findByText('Visited Kyoto station')).toBeInTheDocument();
  });

  it('renders the Magi recap, source episodes, and readable event previews', async () => {
    const user = userEvent.setup();
    renderPage();

    await openLaunchExperience(user);
    expect(await screen.findByText('Generated Japan recap')).toBeInTheDocument();
    expect(screen.getByText("Magi's recap")).toBeInTheDocument();
    expect(screen.getByText('Source chapters')).toBeInTheDocument();
    expect(screen.getByText('Planning thread')).toBeInTheDocument();

    const events = screen.getByTestId('episode-event-stream');
    expect(within(events).getByText('Visited Kyoto station')).toBeInTheDocument();
    expect(within(events).getByText('Booked the Shinkansen tickets')).toBeInTheDocument();
    expect(within(events).queryByText('evt-1')).not.toBeInTheDocument();

    expect(screen.getAllByText('Asuka').length).toBeGreaterThan(0);
    expect(screen.queryByText('person:asuka')).not.toBeInTheDocument();
    expect(screen.getAllByText('studio').length).toBeGreaterThan(0);
    expect(screen.getAllByText('launch').length).toBeGreaterThan(0);
  });

  it('offers reconsolidation when there are no active experiences', async () => {
    vi.mocked(memoryApi.listExperiences).mockResolvedValueOnce({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    } as never);
    renderPage();

    expect(await screen.findByText('No active experiences yet')).toBeInTheDocument();
    expect(screen.getByText('Magi will form experiences as conversations and activity accumulate. If you already have remembered activity, run a refresh now.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Build experiences now' })).toBeInTheDocument();
  });

  it('reconsolidates experiences from the empty state', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.listExperiences)
      .mockResolvedValueOnce({
        items: [],
        total: 0,
        limit: 100,
        offset: 0,
      } as never)
      .mockResolvedValueOnce({
        items: activeExperiences,
        total: 2,
        limit: 100,
        offset: 0,
      } as never);
    renderPage();

    await user.click(await screen.findByRole('button', { name: 'Build experiences now' }));

    await waitFor(() => {
      expect(memoryApi.reconsolidateEpisodes).toHaveBeenCalledTimes(1);
    });
    expect((await screen.findAllByText('Launch week')).length).toBeGreaterThan(0);
  });

  it('renames the selected experience through the annotation API', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.annotateExperience).mockResolvedValue({
      ...experienceDetail,
      user_label: 'Launch sprint',
      display_title: 'Launch sprint',
    } as never);
    renderPage();

    await openLaunchExperience(user);
    await screen.findByText('Generated Japan recap');
    await user.click(screen.getByRole('button', { name: 'Rename' }));
    await user.clear(screen.getByLabelText('Title'));
    await user.type(screen.getByLabelText('Title'), 'Launch sprint');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(memoryApi.annotateExperience).toHaveBeenCalledWith('exp-1', {
        user_label: 'Launch sprint',
      });
    });
  });

  it('edits the selected recap through the annotation API', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.annotateExperience).mockResolvedValue({
      ...experienceDetail,
      user_note: 'This was more about launch prep than execution.',
      display_description: 'This was more about launch prep than execution.',
    } as never);
    renderPage();

    await openLaunchExperience(user);
    await screen.findByText('Generated Japan recap');
    await user.click(screen.getByRole('button', { name: 'Edit recap' }));
    await user.clear(screen.getByLabelText('Recap'));
    await user.type(screen.getByLabelText('Recap'), 'This was more about launch prep than execution.');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(memoryApi.annotateExperience).toHaveBeenCalledWith('exp-1', {
        user_note: 'This was more about launch prep than execution.',
      });
    });
  });

  it('confirms before regenerating over a user-edited recap', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.getExperience).mockResolvedValue({
      ...experienceDetail,
      user_note: 'Manual recap',
      display_description: 'Manual recap',
      display_source: 'user_override',
    });
    vi.mocked(memoryApi.regenerateExperienceReview).mockResolvedValue({
      ...experienceDetail,
      display_description: 'Fresh generated recap',
      experience_review: {
        summary_id: 'sum-new',
        content: 'Fresh generated recap',
        label: 'Fresh generated title',
        updated_at: 1700200000,
        is_fallback: false,
      },
    });
    renderPage();

    await openLaunchExperience(user);
    await screen.findByText('Manual recap');
    await user.click(screen.getByRole('button', { name: 'Regenerate recap' }));
    expect(screen.getByText('Replace current recap?')).toBeInTheDocument();
    expect(memoryApi.regenerateExperienceReview).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Regenerate now' }));

    await waitFor(() => {
      expect(memoryApi.regenerateExperienceReview).toHaveBeenCalledWith('exp-1');
    });
    expect((await screen.findAllByText('Fresh generated recap')).length).toBeGreaterThan(0);
  });

  it('hides the selected experience after confirmation', async () => {
    const user = userEvent.setup();
    renderPage();

    await openLaunchExperience(user);
    await screen.findByText('Generated Japan recap');
    await user.click(screen.getByRole('button', { name: 'Hide' }));
    expect(screen.getByText('Hide this experience?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Hide experience' }));

    await waitFor(() => {
      expect(memoryApi.hideExperience).toHaveBeenCalledWith('exp-1');
    });
    expect(screen.queryByText('Launch week')).not.toBeInTheDocument();
  });
});
