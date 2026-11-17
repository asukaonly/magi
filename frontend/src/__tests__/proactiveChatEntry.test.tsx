import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { SuggestedChatDraft } from '@/components/chat/SuggestedChatDraft';
import { QuietThoughtSuggestion } from '@/components/chat/QuietThoughtSuggestion';
import { personaThoughtsApi } from '@/api/modules/personaThoughts';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/api/modules/personaThoughts', () => ({ personaThoughtsApi: { share: vi.fn() } }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

it('does not overwrite or send a draft until the user chooses to insert it', () => {
  const insert = vi.fn();
  render(<MemoryRouter initialEntries={[{ pathname: '/chat', state: { suggestedDraft: 'Discuss the earlier thought' } }]}>
    <SuggestedChatDraft disabled={false} onInsert={insert} />
  </MemoryRouter>);
  expect(insert).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'personality.thoughts.insertDraft' }));
  expect(insert).toHaveBeenCalledWith('Discuss the earlier thought');
  expect(screen.queryByText('Discuss the earlier thought')).not.toBeInTheDocument();
});

it('only requests a shared thought after a visible idle period and does not send it', async () => {
  vi.useFakeTimers();
  vi.mocked(personaThoughtsApi.share).mockResolvedValue({ id: 't1', persona_id: 'p1', created_at: 1,
    status: 'active', kind: 'open_question', topic: 'Design', content: 'A question worth considering',
    applicability: 'Design discussion', citations: [] });
  const discuss = vi.fn();
  const view = render(<QuietThoughtSuggestion busy onDiscuss={discuss} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  expect(personaThoughtsApi.share).not.toHaveBeenCalled();
  view.rerender(<QuietThoughtSuggestion busy={false} onDiscuss={discuss} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  expect(personaThoughtsApi.share).toHaveBeenCalledTimes(1);
  expect(screen.getByText('A question worth considering')).toBeInTheDocument();
  expect(discuss).not.toHaveBeenCalled();
});
