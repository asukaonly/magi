import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useMemory } from '@/hooks/useMemory';
import { APP_EVENTS } from '@/constants/events';

const api = vi.hoisted(() => ({
  getStatistics: vi.fn(), getL0Sessions: vi.fn(), getL0Workbench: vi.fn(), getL1Events: vi.fn(),
  getL2Statistics: vi.fn(), getIdentityLinks: vi.fn(), getL2ConflictRules: vi.fn(),
  getL2Relations: vi.fn(), getL2Assertions: vi.fn(), getL2Entities: vi.fn(),
  getL2Mentions: vi.fn(), getL2Snapshots: vi.fn(), getL3Summaries: vi.fn(), getL4Skills: vi.fn(),
}));
vi.mock('@/api/modules/memory', () => ({ memoryApi: api }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => {
  vi.resetAllMocks();
  for (const method of Object.values(api)) method.mockResolvedValue({ items: [], total: 0 });
  api.getIdentityLinks.mockResolvedValue({ links: [] });
  api.getL2ConflictRules.mockResolvedValue([]);
});

it.each([
  ['getL0Sessions', 'loadL0Sessions', 'l0Sessions', 'l0Total'],
  ['getL1Events', 'queryL1Events', 'l1Events', 'l1Total'],
  ['getL2Relations', 'loadL2Relations', 'l2Relations', 'l2RelationsTotal'],
  ['getL2Assertions', 'loadL2Assertions', 'l2Assertions', 'l2AssertionsTotal'],
  ['getL2Entities', 'loadL2Entities', 'l2Entities', 'l2EntitiesTotal'],
  ['getL2Mentions', 'loadL2Mentions', 'l2Mentions', 'l2MentionsTotal'],
  ['getL2Snapshots', 'loadL2Snapshots', 'l2Snapshots', 'l2SnapshotsTotal'],
  ['getL3Summaries', 'loadL3Summaries', 'l3Summaries', 'l3Total'],
  ['getL4Skills', 'loadL4Skills', 'l4Skills', 'l4Total'],
] as const)('%s keeps the latest page and count when a previous page finishes last', async (method, loader, state, count) => {
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  let finish: (value: unknown) => void = () => {};
  api[method].mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let old: Promise<unknown> = Promise.resolve();
  act(() => { old = result.current[loader]({ limit: 1, offset: 0 }); });
  api[method].mockResolvedValueOnce({ items: [{ marker: 'new' }], total: 12 });
  await act(() => result.current[loader]({ limit: 1, offset: 1 }));
  await act(async () => { finish({ items: [{ marker: 'old' }], total: 99 }); await old; });
  expect(result.current[state]).toEqual([{ marker: 'new' }]);
  expect(result.current[count]).toBe(12);
});

it('shares admission between the initial L2 batch and a newer filtered entity read', async () => {
  let finish: (value: unknown) => void = () => {};
  api.getL2Entities.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'l2' }));
  await waitFor(() => expect(api.getL2Entities).toHaveBeenCalledOnce());
  api.getL2Entities.mockResolvedValueOnce({ items: [{ entity_id: 'new' }], total: 1 });
  await act(() => result.current.loadL2Entities({ query: 'new query' }));
  await act(async () => { finish({ items: [{ entity_id: 'old' }], total: 4 }); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.l2Entities).toEqual([{ entity_id: 'new' }]);
  expect(result.current.l2EntitiesTotal).toBe(1);
});

it('ignores an old L1 failure after a newer successful query', async () => {
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  let reject: (reason: Error) => void = () => {};
  api.getL1Events.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
  let old: Promise<unknown> = Promise.resolve();
  act(() => { old = result.current.queryL1Events({ query: 'old' }); });
  await act(() => result.current.queryL1Events({ query: 'new' }));
  await act(async () => { reject(new Error('Late failure')); await old; });
  expect(result.current.l1LoadFailed).toBe(false);
  expect(result.current.loading).toBe(false);
});

it('invalidates a pending workbench when its session is deselected', async () => {
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  let finish: (value: unknown) => void = () => {};
  api.getL0Workbench.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  act(() => result.current.selectSession('old-session'));
  await waitFor(() => expect(api.getL0Workbench).toHaveBeenCalledOnce());
  act(() => result.current.selectSession(null));
  await act(async () => { finish({ session_id: 'old-session' }); });
  expect(result.current.l0Workbench).toBeNull();
  expect(result.current.selectedSessionId).toBeNull();
});

it('retains the current workbench when the same session is selected again', async () => {
  api.getL0Workbench.mockResolvedValue({ session_id: 'current' });
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.selectSession('current'));
  await waitFor(() => expect(result.current.l0Workbench).toEqual({ session_id: 'current' }));
  act(() => result.current.selectSession('current'));
  expect(result.current.l0Workbench).toEqual({ session_id: 'current' });
  expect(api.getL0Workbench).toHaveBeenCalledOnce();
});

it('does not load a departed session after an older refresh finishes its list step', async () => {
  api.getL0Workbench.mockImplementation(async sessionId => ({ session_id: sessionId }));
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.selectSession('old'));
  await waitFor(() => expect(result.current.l0Workbench).toEqual({ session_id: 'old' }));
  let finish: (value: unknown) => void = () => {};
  api.getL0Sessions.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let pending = Promise.resolve();
  act(() => { pending = result.current.refresh('l0'); });
  await waitFor(() => expect(api.getL0Sessions).toHaveBeenCalledOnce());
  act(() => result.current.selectSession('new'));
  await waitFor(() => expect(result.current.l0Workbench).toEqual({ session_id: 'new' }));
  await act(async () => { finish({ items: [], total: 0 }); await pending; });
  expect(result.current.selectedSessionId).toBe('new');
  expect(result.current.l0Workbench).toEqual({ session_id: 'new' });
  expect(api.getL0Workbench).toHaveBeenCalledTimes(2);
});

it('refreshes only loaded resource snapshots and retains the latest query and page', async () => {
  const { result } = renderHook(() => useMemory({ initialLoadScope: 'overview' }));
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.loadL2Entities({ query: 'latest filter', offset: 50, limit: 25 }));
  api.getL2Entities.mockResolvedValue({ items: [{ entity_id: 'remote-change' }], total: 78 });
  act(() => window.dispatchEvent(new Event(APP_EVENTS.CENTER_STATE_CHANGED)));
  await waitFor(() => expect(result.current.l2EntitiesTotal).toBe(78), { timeout: 3000 });
  expect(api.getL2Entities).toHaveBeenLastCalledWith({ query: 'latest filter', offset: 50, limit: 25 });
  expect(api.getL3Summaries).not.toHaveBeenCalled();
  expect(api.getL0Sessions).not.toHaveBeenCalled();
  expect(result.current.loading).toBe(false);
});
