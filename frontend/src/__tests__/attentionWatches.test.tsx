import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { attentionWatchesApi, type AttentionWatch } from '@/api/modules/attentionWatches';
import { AttentionWatchesPage } from '@/pages/tasks-pages/AttentionWatchesPage';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
vi.mock('@/components/memory/evidence/MemoryEvidenceButton', () => ({ MemoryEvidenceButton: () => <button>Evidence</button> }));
const watch: AttentionWatch = { id: 'w1', title: 'Version release', condition: 'Tell me when version 2 ships', sources: ['chat'],
  expires_at: null, item_id: null, version: 1, status: 'active', created_at: 1, updated_at: 1,
  last_checked_at: null, check_status: 'waiting', result: null };
beforeEach(() => vi.restoreAllMocks());
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AttentionWatchesPage /></MemoryRouter></QueryClientProvider>);
}

it('requires an explicit condition and source before creating a watch', async () => {
  vi.spyOn(attentionWatchesApi, 'list').mockResolvedValue({ items: [], sources: ['chat'], next_offset: null });
  vi.spyOn(attentionWatchesApi, 'get').mockResolvedValue(watch);
  const mutate = vi.spyOn(attentionWatchesApi, 'mutate').mockResolvedValue({ watch, replayed: false });
  show();
  await screen.findByText('attentionWatches.empty');
  fireEvent.click(screen.getByRole('button', { name: 'attentionWatches.create' }));
  expect(screen.getByRole('button', { name: 'attentionWatches.save' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('attentionWatches.fields.title'), { target: { value: watch.title } });
  fireEvent.change(screen.getByLabelText('attentionWatches.fields.condition'), { target: { value: watch.condition } });
  expect(screen.getByRole('button', { name: 'attentionWatches.save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'attentionWatches.save' }));
  await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  expect(mutate.mock.calls[0]?.[0]).toMatchObject({ action: 'create', expected_version: 0,
    fields: { title: watch.title, condition: watch.condition, sources: ['chat'], expires_at: null } });
  await screen.findByText(watch.title);
});

it('pauses the current version', async () => {
  const list = vi.spyOn(attentionWatchesApi, 'list').mockResolvedValue({ items: [watch], sources: ['chat'], next_offset: null });
  vi.spyOn(attentionWatchesApi, 'get').mockResolvedValue({ ...watch, status: 'paused', version: 2 });
  const mutate = vi.spyOn(attentionWatchesApi, 'mutate').mockImplementation(async () => {
    list.mockResolvedValue({ items: [{ ...watch, status: 'paused', version: 2 }], sources: ['chat'], next_offset: null });
    return { watch: { ...watch, status: 'paused', version: 2 }, replayed: false };
  });
  show();
  await screen.findByText(watch.title);
  fireEvent.click(screen.getByRole('button', { name: 'attentionWatches.pause' }));
  await screen.findByText('attentionWatches.statuses.paused');
  expect(mutate.mock.calls[0]?.[0]).toMatchObject({ action: 'pause', watch_id: 'w1', expected_version: 1 });
});

it('presents a matched result with evidence and a discussion action', async () => {
  vi.spyOn(attentionWatchesApi, 'list').mockResolvedValue({ items: [{ ...watch, status: 'matched', check_status: 'matched',
    result: { matched: true, summary: 'Version 2 has shipped.', next_step: '', citations: [{ event_id: 'e1', quote: 'shipped' }] } }], sources: ['chat'], next_offset: null });
  show();
  await screen.findByText('Version 2 has shipped.');
  expect(screen.getByRole('button', { name: 'Evidence' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'attentionWatches.discuss' })).toBeInTheDocument();
});

it('does not present read failures as an empty watch list', async () => {
  vi.spyOn(attentionWatchesApi, 'list').mockRejectedValue(new Error('offline'));
  show();
  await screen.findByText('attentionWatches.loadFailed');
  expect(screen.queryByText('attentionWatches.empty')).not.toBeInTheDocument();
});

it('withdraws the result badge and discussion action when supporting evidence changes', async () => {
  vi.spyOn(attentionWatchesApi, 'list').mockResolvedValue({ items: [{ ...watch, status: 'matched', check_status: 'invalidated' }], sources: ['chat'], next_offset: null });
  show();
  await screen.findByText('attentionWatches.statuses.withdrawn');
  expect(screen.queryByText('attentionWatches.statuses.matched')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'attentionWatches.discuss' })).not.toBeInTheDocument();
  expect(screen.getByText('attentionWatches.checks.invalidated')).toBeInTheDocument();
});

it('lets the user replace a source that no longer has authorized material', async () => {
  vi.spyOn(attentionWatchesApi, 'list').mockResolvedValue({ items: [watch], sources: ['notes'], next_offset: null });
  show();
  await screen.findByText(watch.title);
  fireEvent.click(screen.getByRole('button', { name: 'attentionWatches.edit' }));
  expect(screen.getByText('attentionWatches.sourceUnavailable')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'attentionWatches.save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'chat' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'notes' }));
  expect(screen.queryByText('attentionWatches.sourceUnavailable')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'attentionWatches.save' })).toBeEnabled();
});

it('rejects malformed records, wrong identities and empty mutation receipts', async () => {
  const get = vi.spyOn(api, 'get').mockResolvedValue({ success: true, message: '', data: { ...watch, id: 'other' } });
  await expect(attentionWatchesApi.get('w1')).rejects.toThrow('identity mismatch');
  get.mockResolvedValue({ success: true, message: '', data: { items: [{ ...watch, status: 'unknown' }], sources: ['chat'], next_offset: null } });
  await expect(attentionWatchesApi.list(0)).rejects.toThrow();
  vi.spyOn(api, 'post').mockResolvedValue({ success: true, message: '', data: { watch: null, replayed: false } });
  await expect(attentionWatchesApi.mutate({ request_id: 'a', action: 'create' })).rejects.toThrow('no result');
});
