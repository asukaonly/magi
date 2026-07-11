import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import {
  MemoryEpisodesPage,
  MemoryExperienceDetailPage,
  MemoryExperienceDraftPage,
} from '@/pages/memory-pages/MemoryEpisodesPage';
import { memoryApi } from '@/api/modules/memory';
import type { L2ExperienceReviewDetail, L2ExperienceSeed, L2ExperienceWithReview } from '@/api/modules/memory';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.episodes.title': 'Experiences',
    'memory.episodes.subtitle': 'Recently formed and updated experiences from remembered events.',
    'memory.episodes.sections.list': 'Recently updated experiences',
    'memory.episodes.sections.all': 'All experiences',
    'memory.episodes.sections.detail': 'Experience review',
    'memory.episodes.sections.recap': 'A short recap',
    'memory.episodes.sections.whatHappened': 'Event trail',
    'memory.episodes.sections.sourceEpisodes': 'Source chapters',
    'memory.episodes.sections.featured': 'Worth revisiting',
    'memory.episodes.sections.entities': 'Entities',
    'memory.episodes.sections.relatedObjects': 'Related details',
    'memory.episodes.sections.places': 'Places',
    'memory.episodes.sections.topics': 'Topics',
    'memory.episodes.sections.keywords': 'Keywords',
    'memory.episodes.sortNote': 'Pinned first · Recently updated',
    'memory.episodes.pending.title': 'To organize',
    'memory.episodes.pending.subtitle': 'Magi thinks these fragments may belong together. You decide whether to turn them into an experience.',
    'memory.episodes.pending.count': '{{count}} signals',
    'memory.episodes.pending.clearSignal': 'Clear signal',
    'memory.episodes.pending.fallbackTitle': 'Possible experience',
    'memory.episodes.pending.fallbackDescription': 'These fragments keep returning around {{tags}} in a nearby window, so Magi thinks they may become an experience.',
    'memory.episodes.pending.fallbackDescriptionGeneric': 'These fragments keep returning in a nearby window, so Magi thinks they may become an experience.',
    'memory.episodes.pending.evidenceCount': '{{count}} fragments',
    'memory.episodes.pending.actions.promote': 'Make experience',
    'memory.episodes.pending.actions.reject': 'Not one',
    'memory.episodes.create.title': 'New experience',
    'memory.episodes.create.description': 'Describe the experience you want Magi to help organize.',
    'memory.episodes.create.promptLabel': 'What experience do you want to organize?',
    'memory.episodes.create.promptPlaceholder': 'For example: May 1 to May 10, 2026 · Japan trip',
    'memory.episodes.create.organizing': 'Finding the memories that belong together...',
    'memory.episodes.create.organize': 'Help me organize',
    'memory.episodes.create.error': 'Could not create the experience.',
    'memory.episodes.create.noPromotion': 'The selected chapters were saved for review.',
    'memory.episodes.create.sourceCount': '{{count}} source chapters',
    'memory.episodes.create.selectedCount': '{{count}} selected',
    'memory.episodes.draft.title': 'Experience draft',
    'memory.episodes.draft.autosaved': 'Saved',
    'memory.episodes.draft.back': 'Back to experiences',
    'memory.episodes.draft.recap': 'One-sentence recap',
    'memory.episodes.draft.chapters': 'Chapters',
    'memory.episodes.draft.possible': 'Possibly related',
    'memory.episodes.draft.create': 'Create experience',
    'memory.episodes.draft.chapterTitle': 'Chapter title',
    'memory.episodes.draft.chapterSummary': 'Chapter summary',
    'memory.episodes.draft.removeChapter': 'Remove chapter',
    'memory.episodes.searchLabel': 'Search experiences',
    'memory.episodes.searchPlaceholder': 'Search experiences, places, topics',
    'memory.episodes.filterPinned': 'Filter',
    'memory.episodes.filterPinnedActive': 'Pinned only',
    'memory.episodes.featuredLabel': 'Featured recap',
    'memory.episodes.unknownMonth': 'Undated',
    'memory.episodes.count': '{{count}} active',
    'memory.episodes.eventCount': '{{count}} events',
    'memory.episodes.episodeCount': '{{count}} source episodes',
    'memory.episodes.sourceEpisodeFallback': 'Source chapter {{index}}',
    'memory.episodes.emptyTitle': 'No active experiences yet',
    'memory.episodes.emptyBody': 'Magi will form experiences as conversations and activity accumulate. If you need to refresh them manually, use the Manage page.',
    'memory.episodes.detailEmptyTitle': 'Choose an experience',
    'memory.episodes.detailEmptyBody': 'Open one from the list to inspect its events and impressions.',
    'memory.episodes.noRecap': 'No recap yet.',
    'memory.episodes.noEvents': 'No event memberships found.',
    'memory.episodes.noSourceEpisodes': 'No source episodes found.',
    'memory.episodes.noSearchResults': 'No experiences match those filters.',
    'memory.episodes.detailNotFound': 'Experience not found.',
    'memory.episodes.eventPreviewUnavailable': 'Event preview unavailable',
    'memory.episodes.noTags': 'None yet',
    'memory.episodes.coverAlt': '{{title}} cover',
    'memory.episodes.coverPending': 'Cover pending',
    'memory.episodes.coverHint': 'Use a related image or choose one later.',
    'memory.episodes.coverSelected': 'Selected {{name}}',
    'memory.episodes.actions.changeCover': 'Change cover',
    'memory.episodes.actions.changeCoverFile': 'Choose cover file',
    'memory.episodes.awaitingLabel': 'Waiting for Magi to draft a title...',
    'memory.episodes.fields.title': 'Title',
    'memory.episodes.fields.description': 'Recap',
    'memory.episodes.fields.pinned': 'Pinned',
    'memory.episodes.actions.open': 'Open experience',
    'memory.episodes.actions.backToList': 'Back to experiences',
    'memory.episodes.actions.createExperience': 'New experience',
    'memory.episodes.actions.createExperienceSubmit': 'Create experience',
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
    'memory.episodes.dialogs.regenerateDescription': 'A new recap will be written for this experience.',
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
    listExperienceSeeds: vi.fn(),
    promoteExperienceSeed: vi.fn(),
    rejectExperienceSeed: vi.fn(),
    createExperienceSeed: vi.fn(),
    listExperienceDrafts: vi.fn(),
    organizeExperienceDraft: vi.fn(),
    getExperienceDraft: vi.fn(),
    updateExperienceDraft: vi.fn(),
    createExperienceFromDraft: vi.fn(),
    getExperience: vi.fn(),
    annotateExperience: vi.fn(),
    uploadExperienceCover: vi.fn(),
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

const pendingSeeds: L2ExperienceSeed[] = [
  {
    seed_id: 'seed-1',
    seed_type: 'project',
    status: 'candidate',
    display_title: 'Possible Japan trip planning',
    display_description: 'These fragments cluster around trains, maps, and lodging.',
    display_tags: ['Japan', 'trains'],
    anchor_entity_ids: ['place:japan'],
    anchor_topic_keys: ['topic:travel'],
    time_start: 1700000000,
    time_end: 1700100000,
    confidence: 0.78,
    evidence_count: 4,
  },
  {
    seed_id: 'seed-2',
    seed_type: 'repeated_goal',
    status: 'candidate',
    title: 'Possible model debugging',
    description: 'Magi noticed repeated debugging around the same module.',
    anchor_entity_ids: ['project:craftworld'],
    anchor_topic_keys: ['topic:debugging'],
    time_start: 1700200000,
    time_end: 1700300000,
    confidence: 0.7,
    evidence_count: 3,
  },
];

const sourceEpisodes = [
  {
    episode_id: 'ep-create-1',
    episode_type: 'activity',
    status: 'active',
    display_title: 'Planning thread',
    display_description: 'Drafted the route and hotels.',
    time_start: 1700000000,
    time_end: 1700050000,
    source_event_count: 2,
    primary_entity_ids: [],
    primary_place_ids: [],
    primary_topic_keys: ['topic:travel'],
  },
  {
    episode_id: 'ep-create-2',
    episode_type: 'activity',
    status: 'active',
    label: 'Ticket booking',
    summary: 'Booked Shinkansen tickets.',
    time_start: 1700060000,
    time_end: 1700063000,
    source_event_count: 1,
    primary_entity_ids: [],
    primary_place_ids: [],
    primary_topic_keys: ['topic:travel'],
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
      representative_asset_ref: 'manual-entry-asset://cover.jpg',
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
    {
      episode_id: '2054f7ae-f6f2-4d9e-9c29-7af8760ffbbd',
      episode_type: 'activity',
      status: 'active',
      label: null,
      summary: null,
      time_start: 1700060000,
      time_end: 1700063000,
      source_event_count: 1,
      primary_entity_ids: [],
      primary_place_ids: [],
      primary_topic_keys: [],
      membership_role: 'member',
      membership_confidence: 0.8,
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
      episode_id: '2054f7ae-f6f2-4d9e-9c29-7af8760ffbbd',
      event_id: 'evt-3',
      membership_role: 'member',
      membership_confidence: 0.76,
      added_at: 1700100400,
      timestamp: 1700100400,
      event_type: 'BrowserEvent',
      source: 'chrome',
      content_preview: 'Compared launch copy drafts',
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
    <MemoryRouter initialEntries={['/memory/episodes']}>
      <Routes>
        <Route path="/memory/episodes" element={<MemoryEpisodesPage />} />
        <Route path="/memory/episode-drafts/:draftId" element={<MemoryExperienceDraftPage />} />
        <Route path="/memory/episodes/:experienceId" element={<MemoryExperienceDetailPage />} />
      </Routes>
    </MemoryRouter>
  );

const renderDetailPage = (experienceId = 'exp-1') =>
  render(
    <MemoryRouter initialEntries={[`/memory/episodes/${experienceId}`]}>
      <Routes>
        <Route path="/memory/episodes" element={<MemoryEpisodesPage />} />
        <Route path="/memory/episodes/:experienceId" element={<MemoryExperienceDetailPage />} />
      </Routes>
    </MemoryRouter>
  );

const renderDraftPage = (draftId = 'draft-japan') =>
  render(
    <MemoryRouter initialEntries={[`/memory/episode-drafts/${draftId}`]}>
      <Routes>
        <Route path="/memory/episode-drafts/:draftId" element={<MemoryExperienceDraftPage />} />
        <Route path="/memory/episodes/:experienceId" element={<MemoryExperienceDetailPage />} />
      </Routes>
    </MemoryRouter>
  );

const openLaunchExperience = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole('button', { name: /Open experience: Launch week/ }));
};

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => 'blob:local-cover');
  URL.revokeObjectURL = vi.fn();
  vi.mocked(memoryApi.listExperiences).mockResolvedValue({
    items: [activeExperiences[1], activeExperiences[2], activeExperiences[0]],
    total: 3,
    limit: 100,
    offset: 0,
  } as never);
  vi.mocked(memoryApi.listExperienceSeeds).mockResolvedValue({
    items: pendingSeeds,
    total: 2,
    limit: 6,
    offset: 0,
  } as never);
  vi.mocked(memoryApi.promoteExperienceSeed).mockResolvedValue({
    seed_id: 'seed-1',
    promoted_experience_id: 'exp-promoted',
    experience: null,
  } as never);
  vi.mocked(memoryApi.rejectExperienceSeed).mockResolvedValue({
    seed_id: 'seed-1',
    seed: { ...pendingSeeds[0], status: 'rejected' },
  } as never);
  vi.mocked(memoryApi.createExperienceSeed).mockResolvedValue({
    seed_id: 'seed-manual',
    promoted_experience_id: 'exp-manual',
    experience: null,
  } as never);
  vi.mocked(memoryApi.listExperienceDrafts).mockResolvedValue({
    items: [], total: 0, limit: 20, offset: 0,
  } as never);
  const draft = {
    draft_id: 'draft-japan',
    status: 'editing',
    query_text: '2026年5月1日到10日 日本旅行',
    title: '2026年5月 日本旅行',
    one_sentence_review: '从东京走到京都、奈良和大阪的一段旅行。',
    time_start: 1777564800,
    time_end: 1778428799,
    chapters: [{
      chapter_id: 'chapter-1',
      title: '出发前，把路线定下来',
      summary: '比较新干线车票和住宿，把第一段行程安排清楚。',
      time_start: 1777564800,
      time_end: 1777651200,
      episode_ids: ['ep-create-1'],
      event_ids: [],
    }],
    possible_evidence: [],
    excluded_evidence: [],
    created_experience_id: null,
    created_at: 1778500000,
    updated_at: 1778500000,
  };
  vi.mocked(memoryApi.organizeExperienceDraft).mockResolvedValue({
    status: 'draft', draft, choices: [], message: null,
  } as never);
  vi.mocked(memoryApi.getExperienceDraft).mockResolvedValue(draft as never);
  vi.mocked(memoryApi.updateExperienceDraft).mockResolvedValue(draft as never);
  vi.mocked(memoryApi.createExperienceFromDraft).mockResolvedValue({
    draft_id: 'draft-japan', experience_id: 'exp-manual', experience: null,
  } as never);
  let currentExperienceDetail = experienceDetail;
  vi.mocked(memoryApi.getExperience).mockImplementation(async () => currentExperienceDetail);
  vi.mocked(memoryApi.annotateExperience).mockResolvedValue(experienceDetail);
  vi.mocked(memoryApi.uploadExperienceCover).mockImplementation(async () => {
    currentExperienceDetail = {
      ...currentExperienceDetail,
      user_cover_asset_ref: 'manual-entry-asset://uploaded-cover.jpg',
    };
    return currentExperienceDetail;
  });
  vi.mocked(memoryApi.regenerateExperienceReview).mockResolvedValue(experienceDetail);
  vi.mocked(memoryApi.hideExperience).mockResolvedValue({
    ...experienceDetail,
    status: 'hidden',
  });
  vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
    items: sourceEpisodes,
    total: sourceEpisodes.length,
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
  it('lists experiences as a focused review index without management controls', async () => {
    renderPage();

    expect((await screen.findAllByText('Launch week')).length).toBeGreaterThan(0);
    expect(screen.queryByText('Recently formed and updated experiences from remembered events.')).not.toBeInTheDocument();
    expect(screen.getByText('Generated research loop')).toBeInTheDocument();
    expect(screen.getByText('Pinned first · Recently updated')).toBeInTheDocument();
    expect(screen.getByText('All experiences')).toBeInTheDocument();
    expect(screen.getByText('November 2023')).toBeInTheDocument();
    expect(screen.getByText('Worth revisiting')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Build experiences now' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Search experiences')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Filter' })).not.toBeInTheDocument();
    expect(screen.getByText('To organize')).toBeInTheDocument();
    expect(screen.getByText('Possible Japan trip planning')).toBeInTheDocument();
    expect(screen.getByText('These fragments cluster around trains, maps, and lodging.')).toBeInTheDocument();

    const experienceButtons = screen.getAllByRole('button', { name: /Open experience:/ });
    expect(experienceButtons.map((button) => button.getAttribute('aria-label'))).toEqual([
      'Open experience: Launch week',
      'Open experience: Generated research loop',
      'Open experience: Earlier browsing',
    ]);
    expect(memoryApi.listExperiences).toHaveBeenCalledWith({ status: 'active', limit: 100, offset: 0 });
    expect(memoryApi.listExperienceSeeds).toHaveBeenCalledWith({ status: 'candidate', limit: 6, offset: 0 });
    expect(memoryApi.listEpisodes).not.toHaveBeenCalled();
    expect(memoryApi.getExperience).not.toHaveBeenCalled();
    expect(screen.queryByText('Visited Kyoto station')).not.toBeInTheDocument();
  });

  it('opens experience details on a dedicated page', async () => {
    const user = userEvent.setup();
    renderPage();

    await openLaunchExperience(user);
    expect(await screen.findByRole('button', { name: 'Back to experiences' })).toBeInTheDocument();
    expect(screen.getByTestId('experience-cover-hero').getAttribute('style')).toContain(
      'manual-entry-asset%3A%2F%2Fcover.jpg'
    );
    expect(screen.getByRole('button', { name: 'Change cover' })).toBeInTheDocument();
    expect(await screen.findByText('Generated Japan recap')).toBeInTheDocument();
    expect(screen.getAllByText('Worth revisiting').length).toBeGreaterThan(0);
  });

  it('renders the recap, source episodes, and readable event previews on the detail page', async () => {
    renderDetailPage();

    expect(await screen.findByText('Generated Japan recap')).toBeInTheDocument();
    expect(screen.getByText('A short recap')).toBeInTheDocument();
    expect(screen.getByText('Source chapters')).toBeInTheDocument();
    expect(screen.getByText('Planning thread')).toBeInTheDocument();

    const events = screen.getByTestId('episode-event-stream');
    expect(within(events).getByText('Visited Kyoto station')).toBeInTheDocument();
    expect(within(events).getByText('Booked the Shinkansen tickets')).toBeInTheDocument();
    expect(within(events).queryByText('evt-1')).not.toBeInTheDocument();
    const sourceEpisodes = screen.getByTestId('experience-source-episodes');
    expect(within(sourceEpisodes).getAllByText('Compared launch copy drafts').length).toBeGreaterThan(0);
    expect(within(sourceEpisodes).queryByText('Source chapter 2')).not.toBeInTheDocument();
    expect(screen.queryByText('2054f7ae-f6f2-4d9e-9c29-7af8760ffbbd')).not.toBeInTheDocument();

    expect(screen.getAllByText('Asuka').length).toBeGreaterThan(0);
    expect(screen.queryByText('person:asuka')).not.toBeInTheDocument();
    expect(screen.getAllByText('studio').length).toBeGreaterThan(0);
    expect(screen.getAllByText('launch').length).toBeGreaterThan(0);
  });

  it('uploads a selected cover and reuses the persisted asset after returning', async () => {
    const user = userEvent.setup();
    renderDetailPage();

    await screen.findByText('Generated Japan recap');
    expect(screen.queryByText('Change cover')).toBeInTheDocument();
    expect(screen.queryByText('The cover slot is ready.')).not.toBeInTheDocument();

    const coverFile = new File(['cover'], 'new-cover.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Choose cover file'), coverFile);

    expect(URL.createObjectURL).toHaveBeenCalledWith(coverFile);
    await waitFor(() => {
      expect(memoryApi.uploadExperienceCover).toHaveBeenCalledWith('exp-1', coverFile);
    });
    expect(screen.getByTestId('experience-cover-hero').getAttribute('style')).toContain(
      encodeURIComponent('manual-entry-asset://uploaded-cover.jpg')
    );
    expect(screen.queryByText('Selected new-cover.png')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Back to experiences' }));
    await openLaunchExperience(user);
    expect(screen.getByTestId('experience-cover-hero').getAttribute('style')).toContain(
      encodeURIComponent('manual-entry-asset://uploaded-cover.jpg')
    );
  });

  it('marks pinned experiences as worth revisiting without forcing a featured hero', async () => {
    renderPage();

    expect((await screen.findAllByText('Launch week')).length).toBeGreaterThan(0);
    expect(screen.getByText('Worth revisiting')).toBeInTheDocument();
    expect(screen.queryByText('Featured recap')).not.toBeInTheDocument();
  });

  it('compresses mechanical activity dumps into a one-sentence recap', async () => {
    vi.mocked(memoryApi.getExperience).mockResolvedValueOnce({
      ...experienceDetail,
      display_description: 'Chrome browsed A - Google Search (visited 2 times); Chrome browsed B - Google Search (visited 3 times); Chrome browsed C - Google Search (visited 2 times)',
      experience_review: {
        summary_id: 'sum-mechanical',
        content: 'Chrome browsed A - Google Search (visited 2 times); Chrome browsed B - Google Search (visited 3 times); Chrome browsed C - Google Search (visited 2 times)',
        label: 'Launch week',
        updated_at: 1700100000,
        is_fallback: false,
      },
    });
    renderDetailPage();

    expect(await screen.findByText('This experience centers on Launch week.')).toBeInTheDocument();
    expect(screen.queryByText(/Chrome browsed A/)).not.toBeInTheDocument();
  });

  it('points empty states to the manage page without inline rebuild controls', async () => {
    vi.mocked(memoryApi.listExperiences).mockResolvedValueOnce({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    } as never);
    vi.mocked(memoryApi.listExperienceSeeds).mockResolvedValueOnce({
      items: [],
      total: 0,
      limit: 6,
      offset: 0,
    } as never);
    renderPage();

    expect(await screen.findByText('No active experiences yet')).toBeInTheDocument();
    expect(screen.getByText('Magi will form experiences as conversations and activity accumulate. If you need to refresh them manually, use the Manage page.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Build experiences now' })).not.toBeInTheDocument();
  });

  it('promotes a pending signal into an experience and refreshes the list', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.listExperienceSeeds)
      .mockResolvedValueOnce({
        items: pendingSeeds,
        total: 2,
        limit: 6,
        offset: 0,
      } as never)
      .mockResolvedValueOnce({
        items: [pendingSeeds[1]],
        total: 1,
        limit: 6,
        offset: 0,
      } as never);
    renderPage();

    await screen.findByText('Possible Japan trip planning');
    await user.click(screen.getAllByRole('button', { name: 'Make experience' })[0]);

    await waitFor(() => {
      expect(memoryApi.promoteExperienceSeed).toHaveBeenCalledWith('seed-1');
    });
    expect(memoryApi.listExperiences).toHaveBeenCalledTimes(2);
  });

  it('organizes a natural-language request into a resumable draft page', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Launch week');
    await user.click(screen.getByRole('button', { name: 'New experience' }));
    await user.type(
      screen.getByLabelText('What experience do you want to organize?'),
      '2026年5月1日到10日 日本旅行',
    );
    await user.click(screen.getByRole('button', { name: 'Help me organize' }));

    await waitFor(() => {
      expect(memoryApi.organizeExperienceDraft).toHaveBeenCalledWith({
        query_text: '2026年5月1日到10日 日本旅行',
      });
    });
    expect(await screen.findByText('Experience draft')).toBeInTheDocument();
    expect(screen.getByDisplayValue('2026年5月 日本旅行')).toBeInTheDocument();
    expect(screen.getByDisplayValue('出发前，把路线定下来')).toBeInTheDocument();
  });

  it('saves draft edits before creating the experience', async () => {
    const user = userEvent.setup();
    renderDraftPage();

    const title = await screen.findByLabelText('Title');
    await user.clear(title);
    await user.type(title, '十天日本旅行');
    const chapterSummary = screen.getByLabelText('Chapter summary');
    await user.clear(chapterSummary);
    await user.type(chapterSummary, '先安排交通和住宿，再按城市回顾旅程。');
    await user.click(screen.getByRole('button', { name: 'Create experience' }));

    await waitFor(() => {
      expect(memoryApi.updateExperienceDraft).toHaveBeenCalledWith(
        'draft-japan',
        expect.objectContaining({
          title: '十天日本旅行',
          chapters: [expect.objectContaining({
            summary: '先安排交通和住宿，再按城市回顾旅程。',
          })],
        }),
      );
      expect(memoryApi.createExperienceFromDraft).toHaveBeenCalledWith('draft-japan');
    });
  });

  it('keeps local draft edits after autosave returns', async () => {
    const user = userEvent.setup();
    renderDraftPage();

    const title = await screen.findByLabelText('Title');
    await user.clear(title);
    await user.type(title, '十天日本旅行');

    await waitFor(() => {
      expect(memoryApi.updateExperienceDraft).toHaveBeenCalled();
    }, { timeout: 1500 });
    expect(title).toHaveValue('十天日本旅行');
  });

  it('dismisses a pending signal from the home page', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Possible Japan trip planning');
    await user.click(screen.getAllByRole('button', { name: 'Not one' })[0]);

    await waitFor(() => {
      expect(memoryApi.rejectExperienceSeed).toHaveBeenCalledWith('seed-1');
    });
    await waitFor(() => {
      expect(screen.queryByText('Possible Japan trip planning')).not.toBeInTheDocument();
    });
  });

  it('renames the selected experience through the annotation API', async () => {
    const user = userEvent.setup();
    vi.mocked(memoryApi.annotateExperience).mockResolvedValue({
      ...experienceDetail,
      user_label: 'Launch sprint',
      display_title: 'Launch sprint',
    } as never);
    renderDetailPage();

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
    renderDetailPage();

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

  it('shows structured review JSON as an editable recap', async () => {
    const user = userEvent.setup();
    const structuredReview = JSON.stringify({
      label: '调试 Tauri 与跑基准测试',
      content: '这段时间主要在调试本地热重载，并穿插跑基准测试。',
      key_topics: ['dev-tauri-hot.sh'],
    }, null, 2);
    vi.mocked(memoryApi.getExperience).mockResolvedValue({
      ...experienceDetail,
      user_note: null,
      display_description: structuredReview,
      experience_review: {
        summary_id: 'sum-structured',
        content: structuredReview,
        label: '调试 Tauri 与跑基准测试',
        updated_at: 1700100000,
        is_fallback: false,
      },
    });
    renderDetailPage();

    expect(await screen.findByText('这段时间主要在调试本地热重载，并穿插跑基准测试。')).toBeInTheDocument();
    expect(screen.queryByText(/key_topics/)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Edit recap' }));

    expect(screen.getByLabelText('Recap')).toHaveValue('这段时间主要在调试本地热重载，并穿插跑基准测试。');
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
    renderDetailPage();

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
    renderDetailPage();

    await screen.findByText('Generated Japan recap');
    await user.click(screen.getByRole('button', { name: 'Hide' }));
    expect(screen.getByText('Hide this experience?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Hide experience' }));

    await waitFor(() => {
      expect(memoryApi.hideExperience).toHaveBeenCalledWith('exp-1');
    });
    expect(await screen.findByText('All experiences')).toBeInTheDocument();
  });

  it('does not display slash-separated fallback labels as experience titles', async () => {
    vi.mocked(memoryApi.listExperiences).mockResolvedValueOnce({
      items: [{
        ...activeExperiences[1],
        display_title: 'gt new horizons / claude code / disc',
        title: 'Untitled experience / Untitled experience',
        magi_interpretation: 'Magi grouped related episode evidence into a narratable memory.',
        experience_review: {
          ...activeExperiences[1].experience_review!,
          label: 'gt new horizons / claude code / disc',
          is_fallback: true,
        },
      }],
      total: 1,
      limit: 100,
      offset: 0,
    } as never);

    renderPage();

    expect(await screen.findByText('Activity around onboarding')).toBeInTheDocument();
    expect(screen.queryByText('gt new horizons / claude code / disc')).not.toBeInTheDocument();
  });
});
