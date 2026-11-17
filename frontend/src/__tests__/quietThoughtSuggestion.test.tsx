import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { QuietThoughtSuggestion } from '@/components/chat/QuietThoughtSuggestion';
import { personaThoughtsApi } from '@/api/modules/personaThoughts';
import { APP_EVENTS } from '@/constants/events';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/api/modules/personaThoughts', () => ({ personaThoughtsApi: { share: vi.fn() } }));
const thought = { id: 't1', persona_id: 'p1', created_at: 1700000000, status: 'active' as const,
  kind: 'perspective' as const, topic: 'Maintenance', content: 'Consider maintenance costs.', applicability: 'Engineering decisions',
  citations: [{ event_id: 'e1', quote: 'maintenance' }] };
const advance = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(personaThoughtsApi.share).mockReset();
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it('finds newly available thoughts after an empty check without remounting chat', async () => {
  vi.mocked(personaThoughtsApi.share).mockResolvedValueOnce(null).mockResolvedValue(thought);
  render(<QuietThoughtSuggestion busy={false} onDiscuss={vi.fn()} />);
  await advance(30_000);
  expect(personaThoughtsApi.share).toHaveBeenCalledTimes(1);
  await advance(30_000);
  expect(screen.getByText(thought.content)).toBeInTheDocument();
  await advance(60_000);
  expect(personaThoughtsApi.share).toHaveBeenCalledTimes(2);
});

it('keeps a visible thought through unrelated center changes', async () => {
  vi.mocked(personaThoughtsApi.share).mockResolvedValue(thought);
  render(<QuietThoughtSuggestion busy={false} onDiscuss={vi.fn()} />);
  await advance(30_000);
  act(() => { window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'notifications' } })); });
  expect(screen.getByText(thought.content)).toBeInTheDocument();
  act(() => { window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'memory' } })); });
  expect(screen.queryByText(thought.content)).not.toBeInTheDocument();
});

it('waits for visible idle time and does not overlap slow checks', async () => {
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  vi.mocked(personaThoughtsApi.share).mockImplementation(() => new Promise(() => {}));
  const view = render(<QuietThoughtSuggestion busy={false} onDiscuss={vi.fn()} />);
  await advance(60_000);
  expect(personaThoughtsApi.share).not.toHaveBeenCalled();
  visibility.mockReturnValue('visible');
  act(() => { document.dispatchEvent(new Event('visibilitychange')); });
  await advance(29_999);
  expect(personaThoughtsApi.share).not.toHaveBeenCalled();
  await advance(60_001);
  expect(personaThoughtsApi.share).toHaveBeenCalledTimes(1);
  const signal = vi.mocked(personaThoughtsApi.share).mock.calls[0][0];
  view.rerender(<QuietThoughtSuggestion busy onDiscuss={vi.fn()} />);
  expect(signal?.aborted).toBe(true);
});
