import { defineChatPageSuite, realtimeListener } from '@/test/chatPageHarness';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { messagesApi } from '@/api';
import { parseConversationHistory } from '@/api/event-contract';
import type { ConversationHistory } from '@/api/modules/messages';
import { ChatPage } from '@/pages/Chat';
import { refreshChatHistory, resetChatReadMemory } from '@/runtime/chat-read-cache';
import { centerLocalStorage, setCenterStorageScope } from '@/runtime/center-storage';
import { useConversationStore } from '@/stores/conversation-store';
import fixtures from '../../../contracts/api/frontend-events-examples.json';

const SESSION_ID = 'session-1';
const CACHE_KEY = 'magi.chat.read-cache.v1';

function history(content: string, options: { revision?: string; before?: string; timestamp?: number } = {}): ConversationHistory {
  return parseConversationHistory({
    ...fixtures.historyPage,
    user_id: 'local_user', session_id: SESSION_ID,
    revision: options.revision ?? 'r1',
    has_more: Boolean(options.before), next_before: options.before ?? null,
    messages: [{
      ...fixtures.message, message_id: content, turn_id: `turn-${content}`,
      role: 'user', kind: 'user', message_kind: 'user', content,
      timestamp: options.timestamp ?? 100,
    }],
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

defineChatPageSuite('ChatPage history pagination', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setCenterStorageScope('history-pagination-center', 'epoch-1');
  });

  it('loads earlier messages through the history button and disables duplicate clicks while pending', async () => {
    const user = userEvent.setup();
    const older = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history('Current head', { before: 'older-page' }))
      .mockReturnValueOnce(older.promise);
    render(<ChatPage />);

    expect(await screen.findByText('Current head')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'chat.loadOlderHistory' }));
    const pendingButton = screen.getByRole('button', { name: 'chat.loadingOlderHistory' });
    expect(pendingButton).toBeDisabled();
    await user.click(pendingButton);
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(2);
    expect(messagesApi.getHistory).toHaveBeenLastCalledWith('local_user', SESSION_ID, { limit: 50, before: 'older-page' });

    await act(async () => { older.resolve(history('Earlier message', { timestamp: 50 })); });

    expect(await screen.findByText('Earlier message')).toBeInTheDocument();
    expect(screen.getByText('Current head')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'chat.loadOlderHistory' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'chat.loadingOlderHistory' })).not.toBeInTheDocument();
    expect(useConversationStore.getState().messagesBySession[SESSION_ID].map((message) => message.content))
      .toEqual(['Earlier message', 'Current head']);
  });

  it('preserves a confirmed realtime reply received while an older history page is pending', async () => {
    const user = userEvent.setup();
    const older = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory)
      .mockResolvedValueOnce(history('Existing user message', { before: 'older-page' }))
      .mockReturnValueOnce(older.promise);
    render(<ChatPage />);
    await screen.findByText('Existing user message');
    await user.click(screen.getByRole('button', { name: 'chat.loadOlderHistory' }));

    act(() => {
      realtimeListener?.({ event: 'agent_response', data: {
        session_id: SESSION_ID, message_id: 'confirmed-live-reply',
        turn_id: 'live-turn', message_kind: 'assistant_final',
        content: 'Confirmed realtime reply', timestamp: 200_000,
      } });
    });
    expect(await screen.findByText('Confirmed realtime reply')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'chat.loadingOlderHistory' })).toBeDisabled();

    await act(async () => { older.resolve(history('Earlier user message', { timestamp: 50 })); });

    expect(await screen.findByText('Earlier user message')).toBeInTheDocument();
    expect(screen.getByText('Existing user message')).toBeInTheDocument();
    expect(screen.getAllByText('Confirmed realtime reply')).toHaveLength(1);
    expect(useConversationStore.getState().messagesBySession[SESSION_ID].find((message) => message.messageId === 'confirmed-live-reply'))
      .toMatchObject({ role: 'assistant', content: 'Confirmed realtime reply', turnId: 'live-turn' });
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(2);
  });

  it.each(['unchanged', 'changed'] as const)('shows a stale disk snapshot until %s server validation completes', async (result) => {
    vi.mocked(messagesApi.getHistory).mockResolvedValueOnce(history('Cached conversation', { before: 'cached-older' }));
    await refreshChatHistory(SESSION_ID);
    expect(centerLocalStorage().getItem(CACHE_KEY)).toContain('Cached conversation');
    resetChatReadMemory();
    const response = deferred<ConversationHistory>();
    vi.mocked(messagesApi.getHistory).mockClear().mockReturnValueOnce(response.promise);
    render(<ChatPage />);

    expect(await screen.findByText('Cached conversation')).toBeInTheDocument();
    expect(screen.getByText('chat.cachedHistory')).toHaveAttribute('role', 'status');
    expect(screen.getByRole('button', { name: 'chat.loadOlderHistory' })).toBeInTheDocument();
    expect(messagesApi.getHistory).toHaveBeenCalledWith('local_user', SESSION_ID, { limit: 50, known_revision: 'r1' });

    const confirmed = result === 'unchanged'
      ? { ...history('Unused conditional body'), messages: [], count: 0, not_modified: true }
      : history('Updated server conversation', { revision: 'r2' });
    await act(async () => { response.resolve(confirmed); });

    await waitFor(() => expect(screen.queryByText('chat.cachedHistory')).not.toBeInTheDocument());
    if (result === 'unchanged') {
      expect(screen.getByText('Cached conversation')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'chat.loadOlderHistory' })).toBeInTheDocument();
      expect(screen.queryByText('Unused conditional body')).not.toBeInTheDocument();
    } else {
      expect(screen.getByText('Updated server conversation')).toBeInTheDocument();
      expect(screen.queryByText('Cached conversation')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'chat.loadOlderHistory' })).not.toBeInTheDocument();
    }
    expect(messagesApi.getHistory).toHaveBeenCalledTimes(1);
  });
});
