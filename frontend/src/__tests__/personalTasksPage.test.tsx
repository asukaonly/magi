import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { PersonalTasksPage } from '@/pages/tasks-pages/PersonalTasksPage';
import { PersonalTaskEditor } from '@/pages/tasks-pages/components/PersonalTaskEditor';
import { personalItem, personalDetail } from './fixtures/personalTasks';

const mocks = vi.hoisted(() => ({list: vi.fn(), get: vi.fn(), mutate: vi.fn(), create: vi.fn(), session: vi.fn(), send: vi.fn(), navigate: vi.fn(), error: vi.fn(), warning: vi.fn(), t: (key: string) => key}));
vi.mock('react-i18next', () => ({useTranslation: () => ({t: mocks.t, i18n: {language: 'en'}})}));
vi.mock('@/api/modules/personalTasks', async (original) => ({...await original<object>(), personalTasksApi: {list: mocks.list, get: mocks.get, mutate: mocks.mutate}}));
vi.mock('@/api/modules/messages', () => ({messagesApi: {createNewSession: mocks.create, getSession: mocks.session, sendMessage: mocks.send}}));
vi.mock('@/hooks/useAppNavigate', () => ({useAppNavigate: () => mocks.navigate}));
vi.mock('@/runtime/config', async (original) => ({...await original<object>(), getRuntimeGeneration: () => 1}));
vi.mock('@/stores/conversation-store', () => ({useConversationStore: {getState: () => ({upsertSession: vi.fn(), setCurrentSessionId: vi.fn()})}}));
vi.mock('sonner', () => ({toast: {error: mocks.error, warning: mocks.warning}}));
vi.mock('@/components/ui/markdown-block', () => ({MarkdownBlock: ({children}: {children: ReactNode}) => <div>{children}</div>}));
vi.mock('@/components/memory/evidence/MemoryEvidenceButton', () => ({MemoryEvidenceButton: () => null}));
vi.mock('@/pages/tasks-pages/TasksPageFrame', () => ({TasksPageFrame: ({children, toolbar, actions}: {children: ReactNode; toolbar: ReactNode; actions: ReactNode}) => <div>{actions}{toolbar}{children}</div>}));

const page = (items = [personalItem()]) => ({items, total: items.length, next_offset: null, counts: {}});
const renderPage = (selected = true) => render(<MemoryRouter initialEntries={[selected ? '/tasks/personal?item=item-one' : '/tasks/personal']}><PersonalTasksPage /></MemoryRouter>);
beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockImplementation(async ({view}: {view: string}) => view === 'projects' ? page([]) : page());
  mocks.get.mockResolvedValue(personalDetail());
  mocks.mutate.mockResolvedValue({item: personalItem({version: 2}), deleted_ids: [], replayed: false, reminders_pending: false});
});

it('records progress with the current version and resulting state', async () => {
  renderPage();
  await screen.findByRole('heading', {name: 'Prepare quote'});
  fireEvent.change(screen.getByRole('textbox', {name: 'personalTasks.progress'}), {target: {value: 'Draft prepared; waiting for review'}});
  fireEvent.click(screen.getByRole('button', {name: 'personalTasks.recordProgress'}));
  await waitFor(() => expect(mocks.mutate).toHaveBeenCalledWith(expect.objectContaining({action: 'progress', item_id: 'item-one', expected_version: 1, fields: {status: 'active'}, note: 'Draft prepared; waiting for review'})));
});

it('requires a visible delete choice and removes the selected item after its receipt', async () => {
  renderPage();
  const detail = await screen.findByRole('dialog', {name: 'Prepare quote'});
  fireEvent.click(within(detail).getByRole('button', {name: 'personalTasks.delete'}));
  expect(mocks.mutate).not.toHaveBeenCalled();
  const confirmation = await screen.findByRole('dialog', {name: 'personalTasks.deleteTitle'});
  mocks.mutate.mockResolvedValue({item: null, deleted_ids: ['item-one'], replayed: false, reminders_pending: false});
  mocks.list.mockResolvedValue(page([]));
  fireEvent.click(within(confirmation).getByRole('button', {name: 'personalTasks.delete'}));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(mocks.mutate).toHaveBeenCalledWith(expect.objectContaining({action: 'delete', item_id: 'item-one', expected_version: 1}));
  expect(await screen.findByText('personalTasks.empty')).toBeInTheDocument();
});

it('passes the exact selected item to ordinary chat and handles a rejected send', async () => {
  mocks.create.mockResolvedValue({success: true, session_id: 'session'});
  mocks.session.mockResolvedValue({session_id: 'session'});
  mocks.send.mockResolvedValue({success: false});
  renderPage();
  fireEvent.click(await screen.findByRole('button', {name: 'personalTasks.continue'}));
  await waitFor(() => expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({personal_task_id: 'item-one', session_id: 'session'})));
  await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  expect(mocks.navigate).not.toHaveBeenCalled();
  const creationId = mocks.create.mock.calls[0][1];
  mocks.send.mockResolvedValue({success: true});
  fireEvent.click(screen.getByRole('button', {name: 'personalTasks.continue'}));
  await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/'));
  expect(mocks.create.mock.calls[1][1]).toBe(creationId);
});

it('ignores stale search results after the user changes the query', async () => {
  let resolveOld!: (value: ReturnType<typeof page>) => void;
  mocks.list.mockImplementation(({view, search}: {view: string; search: string}) => {
    if (view === 'projects') return Promise.resolve(page([]));
    if (search === 'old') return new Promise((resolve) => {resolveOld = resolve;});
    return Promise.resolve(page([personalItem({title: search === 'new' ? 'New match' : 'Initial'})]));
  });
  renderPage(false);
  const input = screen.getByRole('textbox', {name: 'personalTasks.search'});
  fireEvent.change(input, {target: {value: 'old'}});
  await waitFor(() => expect(resolveOld).toBeDefined());
  fireEvent.change(input, {target: {value: 'new'}});
  await screen.findByText('New match');
  await act(async () => resolveOld(page([personalItem({title: 'Stale match'})])));
  expect(screen.queryByText('Stale match')).not.toBeInTheDocument();
});

it('keeps the draft on a version conflict and reuses the request ID for a retry', async () => {
  const saved = vi.fn();
  mocks.mutate.mockRejectedValueOnce({status: 409}).mockResolvedValue({item: personalItem({version: 2}), deleted_ids: [], replayed: true, reminders_pending: false});
  render(<PersonalTaskEditor item={personalItem({parent_id: 'closed-project'})} projects={[]} onSaved={saved} onClose={vi.fn()} />);
  fireEvent.change(screen.getByRole('textbox', {name: 'personalTasks.title'}), {target: {value: 'My edit'}});
  fireEvent.click(screen.getByRole('button', {name: 'personalTasks.save'}));
  await screen.findByRole('alert');
  expect(screen.getByRole('textbox', {name: 'personalTasks.title'})).toHaveValue('My edit');
  expect(screen.getByRole('combobox', {name: 'personalTasks.project'})).toHaveValue('closed-project');
  fireEvent.click(screen.getByRole('button', {name: 'personalTasks.save'}));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(mocks.mutate.mock.calls[1][0].request_id).toBe(mocks.mutate.mock.calls[0][0].request_id);
});

it('does not apply a saved draft after the editor has unmounted', async () => {
  let resolveSave!: (value: unknown) => void;
  mocks.mutate.mockImplementation(() => new Promise((resolve) => {resolveSave = resolve;}));
  const saved = vi.fn();
  const view = render(<PersonalTaskEditor item={personalItem()} projects={[]} onSaved={saved} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', {name: 'personalTasks.save'}));
  view.unmount();
  await act(async () => resolveSave({item: personalItem(), deleted_ids: [], replayed: false, reminders_pending: false}));
  expect(saved).not.toHaveBeenCalled();
});

it('uses the device timezone when assigning the first date to an undated item', async () => {
  const currentOptions = new Intl.DateTimeFormat().resolvedOptions();
  const options = vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({...currentOptions, timeZone: 'Asia/Shanghai'});
  try {
    render(<PersonalTaskEditor item={personalItem({due: null, timezone: 'UTC'})} projects={[]} onSaved={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('personalTasks.defer'), {target: {value: '2030-01-05'}});
    fireEvent.click(screen.getByRole('button', {name: 'personalTasks.save'}));
    await waitFor(() => expect(mocks.mutate).toHaveBeenCalledWith(expect.objectContaining({fields: expect.objectContaining({defer_until: '2030-01-05', timezone: 'Asia/Shanghai'})})));
  } finally { options.mockRestore(); }
});
