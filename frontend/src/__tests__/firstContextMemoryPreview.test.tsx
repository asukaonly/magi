import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { memoryApi } from '@/api/modules/memory';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import { FirstContextMemoryPreview } from '@/components/chat/FirstContextMemoryPreview';
import { APP_EVENTS } from '@/constants/events';
import { DEFAULT_USER_ID } from '@/constants';
import { firstContextEvent, firstContextItem, firstContextPortrait } from './fixtures/firstContextMemory';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { getL1Events: vi.fn() } }));
vi.mock('@/api/modules/memoryPortraitSelf', () => ({ memoryPortraitSelfApi: { get: vi.fn() } }));
vi.mock('@/components/memory/evidence/MemoryEvidenceButton', () => ({
  MemoryEvidenceButton: ({ onChanged }: { onChanged: () => void }) => <button onClick={onChanged}>Sources and correction</button>,
}));

async function mount(language = 'en') {
  const i18n = createInstance();
  await i18n.init({ lng: language, defaultNS: 'app', resources: { en: { app: en }, 'zh-CN': { app: zh } }, interpolation: { escapeValue: false } });
  const ask = vi.fn();
  const content = (sessionId = 'session-1', ids = ['first-context-name']) => <MemoryRouter><I18nextProvider i18n={i18n}>
    <FirstContextMemoryPreview sessionId={sessionId} sourceMessageIds={ids} onAsk={ask} />
  </I18nextProvider></MemoryRouter>;
  return { ask, content, ...render(content()) };
}

describe('first context memory feedback', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(memoryApi.getL1Events).mockResolvedValue({ items: [firstContextEvent], total: 1, limit: 1, offset: 0 });
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue(firstContextPortrait());
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it.each(['en', 'zh-CN'])('shows supported reports and stages a question in %s', async (language) => {
    const { ask } = await mount(language);
    const copy = language === 'en' ? en.chat.firstContextMemory : zh.chat.firstContextMemory;
    expect(await screen.findByText(firstContextItem.text)).toBeVisible();
    expect(screen.getByText(copy.ready)).toBeVisible();
    expect(memoryApi.getL1Events).toHaveBeenCalledWith({ source: 'chat', source_item_id: 'first-context-name', session_id: 'session-1', user_id: DEFAULT_USER_ID, limit: 1 });
    fireEvent.click(screen.getByRole('button', { name: copy.tryRecall }));
    expect(ask).toHaveBeenCalledWith(expect.stringContaining(firstContextItem.text));
    expect(document.body.textContent).not.toContain('chat.firstContextMemory.');
  });

  it('excludes inference, partial facts, unrelated evidence and review candidates', async () => {
    const payload = firstContextPortrait([
      firstContextItem,
      { ...firstContextItem, id: 'unrelated', text: 'Unrelated', basis_refs: ['event:old'] },
      { ...firstContextItem, id: 'inferred', text: 'Inferred', evidence_basis: 'inferred' },
      { ...firstContextItem, id: 'partial', text: 'Partial', display_status: 'partial' },
      { ...firstContextItem },
    ]);
    payload.self_view.review.items = [{ ...firstContextItem, id: 'review', text: 'Needs review' }];
    payload.self_view.recent.items = [{ ...firstContextItem, id: 'recent', text: 'Recent self report' }];
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue(payload);
    await mount();
    expect(await screen.findByText('Recent self report')).toBeVisible();
    expect(screen.getByText(en.chat.firstContextMemory.recent)).toBeVisible();
    for (const text of ['Unrelated', 'Inferred', 'Partial', 'Needs review']) expect(screen.queryByText(text)).toBeNull();
    expect(screen.getAllByText(firstContextItem.text)).toHaveLength(1);
  });

  it.each(['stale', 'empty', 'wrong-source', 'wrong-message', 'assistant'])('bounds checks without claiming usable memory for %s', async (reason) => {
    vi.useFakeTimers();
    if (reason === 'stale') vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({ ...firstContextPortrait(), is_stale: true });
    if (reason === 'empty') vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue(firstContextPortrait([]));
    if (reason === 'wrong-source') vi.mocked(memoryApi.getL1Events).mockResolvedValue({ items: [{ ...firstContextEvent, source: 'plugin' }], total: 1, limit: 1, offset: 0 });
    if (reason === 'wrong-message') vi.mocked(memoryApi.getL1Events).mockResolvedValue({ items: [{ ...firstContextEvent, source_item_id: 'other' }], total: 1, limit: 1, offset: 0 });
    if (reason === 'assistant') vi.mocked(memoryApi.getL1Events).mockResolvedValue({ items: [{ ...firstContextEvent, author_type: 'assistant' }], total: 1, limit: 1, offset: 0 });
    const { unmount } = await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(6);
    expect(screen.getByText(en.chat.firstContextMemory.pending)).toBeVisible();
    expect(screen.queryByText(firstContextItem.text)).toBeNull();
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(6);
  });

  it('reports invalid responses as errors and allows explicit retry', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValueOnce({ ...firstContextPortrait(), is_stale: 'false' } as never);
    await mount();
    expect(await screen.findByText(en.chat.firstContextMemory.error)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: en.chat.firstContextMemory.refresh }));
    expect(await screen.findByText(firstContextItem.text)).toBeVisible();
  });

  it('refreshes through the existing correction owner', async () => {
    await mount();
    await screen.findByText(firstContextItem.text);
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue(firstContextPortrait([{ ...firstContextItem, text: 'Corrected self report' }]));
    fireEvent.click(screen.getByRole('button', { name: 'Sources and correction' }));
    expect(await screen.findByText('Corrected self report')).toBeVisible();
    expect(screen.queryByText(firstContextItem.text)).toBeNull();
  });

  it('ignores late responses from the previous conversation', async () => {
    let finish!: (value: ReturnType<typeof firstContextPortrait>) => void;
    vi.mocked(memoryPortraitSelfApi.get).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { rerender, content } = await mount();
    rerender(content('session-2', ['second-message']));
    await waitFor(() => expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(2));
    await act(async () => { finish(firstContextPortrait()); });
    expect(screen.queryByText(firstContextItem.text)).toBeNull();
  });

  it('clears displayed evidence immediately and ignores an in-flight read during memory clearing', async () => {
    await mount();
    await screen.findByText(firstContextItem.text);
    let finish!: (value: ReturnType<typeof firstContextPortrait>) => void;
    vi.mocked(memoryPortraitSelfApi.get).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    act(() => window.dispatchEvent(new CustomEvent(APP_EVENTS.CENTER_STATE_CHANGED, { detail: { resource: 'memory' } })));
    await waitFor(() => expect(memoryPortraitSelfApi.get).toHaveBeenCalledTimes(2));
    act(() => window.dispatchEvent(new Event(APP_EVENTS.MEMORY_CLEAR_STARTED)));
    await act(async () => { finish(firstContextPortrait()); });
    expect(screen.queryByText(firstContextItem.text)).toBeNull();
    expect(screen.getByText(en.chat.firstContextMemory.pending)).toBeVisible();
  });
});
