import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
      if (params?.message) {
        return `${key}:${params.message}`;
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
    listItems: vi.fn(),
    getEvent: vi.fn(),
    createManualEntry: vi.fn(),
    requestSync: vi.fn(),
    requestReanalysis: vi.fn(),
  },
}));

const TIMELINE_ITEMS = [
  {
    item_id: 'summary:day-2026-03-18',
    item_type: 'summary',
    time_start: 1710000600,
    time_end: 1710003600,
    sort_time: 1710003600,
    primary_event_id: null,
    primary_summary_id: 'day-2026-03-18',
    source_event_ids: ['timeline-1', 'timeline-2'],
    source_summary_ids: ['day-2026-03-18'],
    display_payload: {
      title: 'Daily Reflection',
      summary: 'A steady day of research and journaling.',
      summary_type: 'daily',
      summary_category: 'reflection',
      key_topics: ['research', 'journal'],
      key_entities: ['EVA', '明日香'],
      source_event_count: 2,
    },
    projection_version: 1,
    generated_at: 1710003601,
  },
  {
    item_id: 'event:timeline-1',
    item_type: 'event',
    time_start: 1710000000,
    time_end: 1710000000,
    sort_time: 1710000000,
    primary_event_id: 'timeline-1',
    primary_summary_id: null,
    source_event_ids: ['timeline-1'],
    source_summary_ids: [],
    display_payload: {
      title: 'Visited EVA design archive',
      summary: 'Spent time reading reference material and screenshots.',
      source_type: 'browser_history',
      source_item_id: 'history-1',
      event_type: 'BROWSER_CAPTURE',
      retention_mode: 'analyze_only',
      raw_payload_ref: null,
      content_blocks: [{ kind: 'text', value: 'Looked through multiple entries.' }],
      entities: [{ id: 'topic:eva', label: 'EVA', type: 'topic' }],
      tags: ['reference', 'design'],
      provenance: { sensor_id: 'browser_history' },
    },
    projection_version: 1,
    generated_at: 1710000002,
  },
  {
    item_id: 'event:timeline-2',
    item_type: 'event',
    time_start: 1710001000,
    time_end: 1710001000,
    sort_time: 1710001000,
    primary_event_id: 'timeline-2',
    primary_summary_id: null,
    source_event_ids: ['timeline-2'],
    source_summary_ids: [],
    display_payload: {
      title: 'Evening reflection',
      summary: 'Wrote down a calm summary after work.',
      source_type: 'manual_journal',
      source_item_id: 'manual-2',
      event_type: 'MANUAL_JOURNAL',
      retention_mode: 'retain_raw',
      raw_payload_ref: '/tmp/evening-note.md',
      content_blocks: [{ kind: 'text', value: 'Today felt steady and focused.' }],
      entities: [{ id: 'person:asuka', label: '明日香', type: 'person' }],
      tags: ['journal'],
      provenance: { sensor_id: 'manual_journal' },
    },
    projection_version: 1,
    generated_at: 1710001002,
  },
];

const TIMELINE_DETAIL = {
  event_id: 'timeline-2',
  source_type: 'manual_journal',
  source_item_id: 'manual-2',
  occurred_at: 1710001000,
  captured_at: 1710001001,
  title: 'Evening reflection',
  summary: 'Wrote down a calm summary after work.',
  retention_mode: 'retain_raw',
  raw_payload_ref: '/tmp/evening-note.md',
  content_blocks: [{ kind: 'text', value: 'Today felt steady and focused.' }],
  entities: [{ id: 'person:asuka', label: '明日香', type: 'person' }],
  tags: ['journal'],
  privacy_labels: [],
  processing_status: { stored: true, analyzed: true },
  provenance: { sensor_id: 'manual_journal' },
  retention: {
    mode: 'retain_raw',
    retained: true,
    raw_payload_ref: '/tmp/evening-note.md',
    content_block_count: 1,
  },
  graph_evidence: [
    {
      subject_id: 'user:self',
      predicate: 'LIKES',
      object_id: 'person:asuka',
      confidence: 0.86,
      evidence_event_ids: ['timeline-2'],
    },
  ],
};

describe('timeline page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(timelineApi.listItems).mockResolvedValue({
      items: TIMELINE_ITEMS,
      count: TIMELINE_ITEMS.length,
    } as any);
    vi.mocked(timelineApi.getEvent).mockResolvedValue(TIMELINE_DETAIL as any);
    vi.mocked(timelineApi.createManualEntry).mockResolvedValue({
      ...TIMELINE_DETAIL,
      event_id: 'timeline-created',
      title: 'Night walk',
      summary: 'Captured the walk home.',
      content_blocks: [
        { kind: 'text', value: 'The street was quiet.' },
        { kind: 'image', value: '/tmp/night-walk.png' },
      ],
    } as any);
    vi.mocked(timelineApi.requestReanalysis).mockResolvedValue({
      queued: true,
      event_id: 'timeline-2',
      event: TIMELINE_DETAIL,
    } as any);
  });

  it('renders projection items, refetches by range, and filters event cards by source', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    expect(await screen.findByText('Daily Reflection')).toBeInTheDocument();
    expect(await screen.findByText('Visited EVA design archive')).toBeInTheDocument();
    expect(screen.getByText('Evening reflection')).toBeInTheDocument();
    expect(timelineApi.listItems).toHaveBeenCalledWith({ limit: 80, range: 'all' });

    fireEvent.change(screen.getByRole('combobox', { name: 'timeline.filters.range' }), {
      target: { value: '7d' },
    });

    await waitFor(() => expect(timelineApi.listItems).toHaveBeenLastCalledWith({ limit: 80, range: '7d' }));

    fireEvent.change(screen.getByRole('combobox', { name: 'timeline.filters.source' }), {
      target: { value: 'manual_journal' },
    });

    expect(screen.getByText('Evening reflection')).toBeInTheDocument();
    expect(screen.queryByText('Visited EVA design archive')).not.toBeInTheDocument();
    expect(screen.queryByText('Daily Reflection')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'timeline.filters.clear' }));
    expect(await screen.findByText('Visited EVA design archive')).toBeInTheDocument();
    expect(screen.getByText('Daily Reflection')).toBeInTheDocument();
  });

  it('expands a card inline to show retention and derived evidence', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    const manualCard = (await screen.findByText('Evening reflection')).closest('article');
    expect(manualCard).not.toBeNull();
    await user.click(within(manualCard as HTMLElement).getByRole('button', { name: 'timeline.feed.showDetails' }));

    await waitFor(() => expect(timelineApi.getEvent).toHaveBeenCalledWith('timeline-2'));
    expect(await screen.findByText('LIKES')).toBeInTheDocument();
    expect(screen.getByText('person:asuka')).toBeInTheDocument();
    expect(screen.getByText('/tmp/evening-note.md')).toBeInTheDocument();
    expect(screen.getAllByText('timeline.retention.retainRaw').length).toBeGreaterThan(0);
  });

  it('creates a manual journal entry with text and image references', async () => {
    const user = userEvent.setup();
    vi.mocked(timelineApi.listItems)
      .mockResolvedValueOnce({
        items: TIMELINE_ITEMS,
        count: TIMELINE_ITEMS.length,
      } as any)
      .mockResolvedValueOnce({
        items: [
          {
            item_id: 'event:timeline-created',
            item_type: 'event',
            time_start: 1710002000,
            time_end: 1710002000,
            sort_time: 1710002000,
            primary_event_id: 'timeline-created',
            primary_summary_id: null,
            source_event_ids: ['timeline-created'],
            source_summary_ids: [],
            display_payload: {
              title: 'Night walk',
              summary: 'Captured the walk home.',
              source_type: 'manual_journal',
              source_item_id: 'manual-created',
              retention_mode: 'retain_raw',
              raw_payload_ref: null,
              content_blocks: [
                { kind: 'text', value: 'The street was quiet.' },
                { kind: 'image', value: '/tmp/night-walk.png' },
              ],
              entities: [],
              tags: ['journal'],
              provenance: { sensor_id: 'manual_journal' },
            },
            projection_version: 1,
            generated_at: 1710002001,
          },
          ...TIMELINE_ITEMS,
        ],
        count: TIMELINE_ITEMS.length + 1,
      } as any);
    render(<TimelinePage />);

    await user.click(await screen.findByRole('button', { name: 'timeline.actions.addEntry' }));
    await user.type(screen.getByLabelText('timeline.composer.title'), 'Night walk');
    await user.type(screen.getByLabelText('timeline.composer.summary'), 'Captured the walk home.');
    await user.type(screen.getByLabelText('timeline.composer.text'), 'The street was quiet.');
    await user.type(screen.getByLabelText('timeline.composer.imageRef'), '/tmp/night-walk.png');
    await user.click(screen.getByRole('button', { name: 'timeline.composer.addImage' }));
    await user.click(screen.getByRole('button', { name: 'timeline.composer.submit' }));

    await waitFor(() =>
      expect(timelineApi.createManualEntry).toHaveBeenCalledWith({
        title: 'Night walk',
        summary: 'Captured the walk home.',
        text: 'The street was quiet.',
        image_refs: ['/tmp/night-walk.png'],
      })
    );

    await waitFor(() => expect(timelineApi.listItems).toHaveBeenLastCalledWith({ limit: 80, range: 'all' }));
    expect(await screen.findByText('Night walk')).toBeInTheDocument();
  });
});
