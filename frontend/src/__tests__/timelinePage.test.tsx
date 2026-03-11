import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TimelinePage } from '@/pages/Timeline';
import { timelineApi } from '@/api/modules/timeline';

vi.mock('@/api/modules/timeline', () => ({
  timelineApi: {
    listEvents: vi.fn(),
    getEvent: vi.fn(),
    createManualEntry: vi.fn(),
    requestSync: vi.fn(),
    requestReanalysis: vi.fn(),
  },
}));

const TIMELINE_EVENTS = [
  {
    event_id: 'timeline-1',
    source_type: 'browser_history',
    source_item_id: 'history-1',
    occurred_at: 1710000000,
    captured_at: 1710000001,
    title: 'Visited EVA design archive',
    summary: 'Spent time reading reference material and screenshots.',
    retention_mode: 'analyze_only',
    raw_payload_ref: null,
    content_blocks: [{ kind: 'text', value: 'Looked through multiple entries.' }],
    entities: [{ id: 'topic:eva', label: 'EVA', type: 'topic' }],
    tags: ['reference', 'design'],
    privacy_labels: [],
    processing_status: { stored: true, analyzed: true },
    provenance: { sensor_id: 'browser_history' },
    retention: {
      mode: 'analyze_only',
      retained: false,
      raw_payload_ref: null,
      content_block_count: 1,
    },
  },
  {
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
  },
];

const TIMELINE_DETAIL = {
  ...TIMELINE_EVENTS[1],
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
    vi.mocked(timelineApi.listEvents).mockResolvedValue({
      events: TIMELINE_EVENTS,
      count: TIMELINE_EVENTS.length,
    } as any);
    vi.mocked(timelineApi.getEvent).mockResolvedValue(TIMELINE_DETAIL as any);
    vi.mocked(timelineApi.createManualEntry).mockResolvedValue({
      ...TIMELINE_EVENTS[1],
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

  it('renders feed cards from the timeline API and filters by source', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    expect(await screen.findByText('Visited EVA design archive')).toBeInTheDocument();
    expect(screen.getByText('Evening reflection')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox', { name: 'timeline.filters.source' }), {
      target: { value: 'manual_journal' },
    });

    expect(screen.getByText('Evening reflection')).toBeInTheDocument();
    expect(screen.queryByText('Visited EVA design archive')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'timeline.filters.clear' }));
    expect(await screen.findByText('Visited EVA design archive')).toBeInTheDocument();
  });

  it('expands a card inline to show retention and derived evidence', async () => {
    const user = userEvent.setup();
    render(<TimelinePage />);

    const detailButtons = await screen.findAllByRole('button', { name: 'timeline.feed.showDetails' });
    await user.click(detailButtons[0]);

    await waitFor(() => expect(timelineApi.getEvent).toHaveBeenCalledWith('timeline-2'));
    expect(await screen.findByText('LIKES')).toBeInTheDocument();
    expect(screen.getByText('person:asuka')).toBeInTheDocument();
    expect(screen.getByText('/tmp/evening-note.md')).toBeInTheDocument();
    expect(screen.getAllByText('timeline.retention.retainRaw').length).toBeGreaterThan(0);
  });

  it('creates a manual journal entry with text and image references', async () => {
    const user = userEvent.setup();
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

    expect(await screen.findByText('Night walk')).toBeInTheDocument();
  });
});
