import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { PersonaThoughts } from '@/components/personality/PersonaThoughts';
import { personaThoughtsApi } from '@/api/modules/personaThoughts';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/api/modules/personaThoughts', () => ({ personaThoughtsApi: { list: vi.fn(), get: vi.fn(), dismiss: vi.fn() } }));
const thought = { id: 't1', persona_id: 'p1', created_at: 1700000000, status: 'active' as const,
  kind: 'perspective' as const, topic: 'Maintenance', content: 'Consider maintenance costs.', applicability: 'Engineering decisions',
  citations: [{ event_id: 'e1', quote: 'maintenance' }] };
const page = { items: [thought], enabled: true, sharing_enabled: false, last_checked_at: null, last_status: null };
function renderThoughts() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><PersonaThoughts personaId="p1" canDiscuss /></MemoryRouter></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(personaThoughtsApi.list).mockResolvedValue(page);
  vi.mocked(personaThoughtsApi.get).mockResolvedValue({ thought, evidence: [{ event_id: 'e1', content: 'Please consider maintenance.', source: 'chat', occurred_at: 1700000000, session_id: 's1' }] });
});
it('shows evidence on demand and removes a suppressed interpretation', async () => {
  renderThoughts();
  await screen.findByText(thought.content);
  expect(personaThoughtsApi.get).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'personality.thoughts.evidence' }));
  await screen.findByText('Please consider maintenance.');
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  vi.mocked(personaThoughtsApi.list).mockResolvedValue({ ...page, items: [] });
  fireEvent.click(screen.getByRole('button', { name: 'personality.thoughts.dismiss' }));
  await waitFor(() => expect(personaThoughtsApi.dismiss).toHaveBeenCalledWith('p1', 't1'));
  await screen.findByText('personality.thoughts.empty');
});
it('distinguishes a failed read from an empty successful result', async () => {
  vi.mocked(personaThoughtsApi.list).mockRejectedValue(new Error('Offline'));
  renderThoughts();
  await screen.findByText('personality.thoughts.loadFailed');
  expect(screen.queryByText('personality.thoughts.empty')).not.toBeInTheDocument();
});
