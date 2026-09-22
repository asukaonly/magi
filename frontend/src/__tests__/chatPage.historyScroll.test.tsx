import { defineChatPageSuite, realtimeListener } from '@/test/chatPageHarness';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { messagesApi } from '@/api';
import { parseConversationHistory } from '@/api/event-contract';
import type { ConversationHistory } from '@/api/modules/messages';
import { ChatPage } from '@/pages/Chat';
import { useConversationStore } from '@/stores/conversation-store';
import fixtures from '../../../contracts/api/frontend-events-examples.json';

function history(content: string, sessionId = 'session-1', before: string | null = null): ConversationHistory {
  return parseConversationHistory({
    ...fixtures.historyPage, user_id: 'local_user', session_id: sessionId,
    revision: 'r1', has_more: before !== null, next_before: before,
    messages: [{ ...fixtures.message, message_id: content, turn_id: `turn-${content}`,
      content, role: 'user', kind: 'user', message_kind: 'user', timestamp: before ? 100 : 50 }],
  });
}

function bounds(top: number, height: number): DOMRect {
  return { top, bottom: top + height, left: 0, right: 500, width: 500, height, x: 0, y: top, toJSON: () => ({}) };
}

async function renderPendingHistory() {
  let resolve!: (page: ConversationHistory) => void;
  const pending = new Promise<ConversationHistory>((done) => { resolve = done; });
  vi.mocked(messagesApi.getHistory)
    .mockResolvedValueOnce(history('Visible message', 'session-1', 'older-page'))
    .mockReturnValueOnce(pending);
  const rendered = render(<ChatPage />);
  const message = await screen.findByText('Visible message');
  const row = message.closest<HTMLElement>('[data-chat-history-row]');
  const timeline = row?.parentElement?.parentElement;
  if (!row || !timeline) throw new Error('Expected a visible history row inside the timeline');
  let contentTop = 150;
  let scrollHeight = 1_000;
  Object.defineProperty(timeline, 'scrollHeight', { configurable: true, get: () => scrollHeight });
  Object.defineProperty(timeline, 'clientHeight', { configurable: true, value: 300 });
  vi.spyOn(timeline, 'getBoundingClientRect').mockImplementation(() => bounds(0, 300));
  vi.spyOn(row, 'getBoundingClientRect').mockImplementation(() => bounds(contentTop - timeline.scrollTop, 100));
  timeline.scrollTop = 100;
  fireEvent.scroll(timeline);
  await userEvent.setup().click(screen.getByRole('button', { name: 'chat.loadOlderHistory' }));
  expect(screen.getByRole('button', { name: 'chat.loadingOlderHistory' })).toBeDisabled();
  return {
    ...rendered, timeline, resolve,
    moveContent: (top: number, height: number) => { contentTop = top; scrollHeight = height; },
  };
}

defineChatPageSuite('ChatPage history scroll ownership', () => {
  it('anchors the visible row when older messages and a realtime reply arrive together', async () => {
    const { timeline, resolve, moveContent } = await renderPendingHistory();
    moveContent(150, 1_200);
    act(() => {
      realtimeListener?.({ event: 'agent_response', data: {
        session_id: 'session-1', message_id: 'new-live-reply', turn_id: 'live-turn',
        message_kind: 'assistant_final', content: 'New reply below the viewport', timestamp: 200_000,
      } });
    });
    expect(await screen.findByText('New reply below the viewport')).toBeInTheDocument();
    moveContent(450, 1_500);
    await act(async () => { resolve(history('Earlier message')); });

    expect(await screen.findByText('Earlier message')).toBeInTheDocument();
    expect(timeline.scrollTop).toBe(400);
  });

  it('keeps a scroll chosen by the reader while the older page is pending', async () => {
    const { timeline, resolve, moveContent } = await renderPendingHistory();
    timeline.scrollTop = 200;
    fireEvent.scroll(timeline);
    moveContent(450, 1_300);
    await act(async () => { resolve(history('Earlier message')); });

    expect(await screen.findByText('Earlier message')).toBeInTheDocument();
    expect(timeline.scrollTop).toBe(200);
  });

  it('does not apply another session anchor after the reader switches conversations', async () => {
    const { timeline, resolve, moveContent } = await renderPendingHistory();
    vi.mocked(messagesApi.getHistory).mockResolvedValue(history('Second session message', 'session-2'));
    act(() => { useConversationStore.getState().setCurrentSessionId('session-2'); });
    expect(await screen.findByText('Second session message')).toBeInTheDocument();
    timeline.scrollTop = 80;
    fireEvent.scroll(timeline);
    moveContent(450, 1_300);
    await act(async () => { resolve(history('Earlier message')); });

    expect(screen.getByText('Second session message')).toBeInTheDocument();
    expect(screen.queryByText('Earlier message')).not.toBeInTheDocument();
    expect(timeline.scrollTop).toBe(80);
  });
});
