import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({ getViewport: vi.fn(), setPanel: vi.fn(), setActivePanel: vi.fn(), entries: vi.fn(), mood: vi.fn(), standout: vi.fn(), cover: vi.fn(), card: vi.fn(), t: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: m.t, i18n: { language: 'en' } }) }));
vi.mock('@/hooks/useAppNavigate', () => ({ useAppNavigate: () => vi.fn() }));
vi.mock('@/stores', () => ({ useChatShellStore: (selector: (state: unknown) => unknown) => selector({ setActivePanel: m.setActivePanel, setTimelinePanel: m.setPanel }) }));
vi.mock('@/api/modules/timeline', () => ({ timelineApi: { getViewport: m.getViewport, getMoodCalendar: m.mood, getStandout: m.standout, setCoverPreference: m.cover } }));
vi.mock('@/api/modules/memory', () => ({ memoryApi: {} }));
vi.mock('@/api/modules/manualEntries', () => ({ manualEntriesApi: { list: m.entries } }));
vi.mock('@/components/timeline/immersive/PeriodCard', () => ({ PeriodCard: (props: { viewport: { marker: string }; dateLabel: string }) => { m.card(props); return <div data-testid="viewport" data-date={props.dateLabel}>{props.viewport.marker}</div>; } }));
vi.mock('@/components/timeline/immersive/HourDetail', () => ({ HourDetail: () => null }));
vi.mock('@/components/timeline/manual-entries/QuickEntrySheet', () => ({ QuickEntrySheet: () => null }));
import { TimelinePage } from '@/pages/Timeline';

const panel = () => m.setPanel.mock.calls.at(-1)![0];
const card = () => m.card.mock.calls.at(-1)![0];
beforeEach(() => { vi.resetAllMocks(); m.getViewport.mockResolvedValue({ marker: 'Initial' }); m.entries.mockResolvedValue([]); m.mood.mockResolvedValue({ days: [] }); m.standout.mockResolvedValue({ items: [] }); });

it('loads the initial viewport once', async () => {
  render(<TimelinePage />);
  await waitFor(() => expect(m.getViewport).toHaveBeenCalledTimes(1));
  expect(await screen.findByTestId('viewport')).toHaveTextContent('Initial');
});

it('retains the current period when an older response finishes last', async () => {
  render(<TimelinePage />);
  await waitFor(() => expect(m.getViewport).toHaveBeenCalledTimes(1));
  let finishA: (value: unknown) => void = () => {};
  let finishB: (value: unknown) => void = () => {};
  m.getViewport.mockImplementationOnce(() => new Promise(resolve => { finishA = resolve; }));
  act(() => panel().onPrevious());
  await waitFor(() => expect(m.getViewport).toHaveBeenCalledTimes(2));
  m.getViewport.mockImplementationOnce(() => new Promise(resolve => { finishB = resolve; }));
  act(() => panel().onPrevious());
  await waitFor(() => expect(m.getViewport).toHaveBeenCalledTimes(3));
  const newestLabel = panel().dateLabel;
  await act(async () => finishB({ marker: 'New period' }));
  expect(screen.getByTestId('viewport')).toHaveTextContent('New period');
  await act(async () => finishA({ marker: 'Old period' }));
  expect(screen.getByTestId('viewport')).toHaveTextContent('New period');
  expect(screen.getByTestId('viewport')).toHaveAttribute('data-date', newestLabel);
});

it('keeps manual entries and sidebar data owned by the current period', async () => {
  let finishEntries: (value: unknown) => void = () => {};
  let finishMood: (value: unknown) => void = () => {};
  m.entries.mockImplementationOnce(() => new Promise(resolve => { finishEntries = resolve; }));
  m.mood.mockImplementationOnce(() => new Promise(resolve => { finishMood = resolve; }));
  render(<TimelinePage />);
  await screen.findByTestId('viewport');
  m.entries.mockResolvedValue([{ entry_id: 'new' }]);
  m.mood.mockResolvedValue({ days: [{ date: 'new' }] });
  act(() => panel().onPrevious());
  await waitFor(() => expect(card().manualEntries).toEqual([{ entry_id: 'new' }]));
  await act(async () => {
    finishEntries([{ entry_id: 'old' }]);
    finishMood({ days: [{ date: 'old' }] });
  });
  expect(card().manualEntries).toEqual([{ entry_id: 'new' }]);
  expect(panel().moodDays).toEqual([{ date: 'new' }]);
});

it('does not apply a cover response to a different period or retain its pending state', async () => {
  let finish: (value: unknown) => void = () => {};
  m.cover.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  render(<TimelinePage />);
  await screen.findByTestId('viewport');
  let pending = Promise.resolve();
  act(() => { pending = card().onChangeCover({ mode: 'auto' }); });
  expect(card().coverSaving).toBe(true);
  act(() => panel().onPrevious());
  await waitFor(() => expect(m.getViewport).toHaveBeenCalledTimes(2));
  await act(async () => { finish({ title: 'Old cover' }); await pending; });
  expect(card().viewport.cover).toBeUndefined();
  expect(card().coverSaving).toBe(false);
});
