import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { OfflineChatView } from '@/components/connections/OfflineChatView';
import i18n from '@/i18n';
import { CHAT_SESSION_KEY, DEFAULT_USER_ID } from '@/constants';
import { centerLocalStorage, centerStorageKey, setCenterStorageScope } from '@/runtime/center-storage';
import { savedOfflineChats, resetChatReadMemory } from '@/runtime/chat-read-cache';
import { advanceBrowserContentGeneration } from '@/lib/browserContentGeneration';
import fixtures from '../../../contracts/api/frontend-events-examples.json';

const { messages } = vi.hoisted(() => ({ messages: { getHistory: vi.fn(), listSessions: vi.fn(), send: vi.fn() } }));
vi.mock('@/api', () => ({ messagesApi: messages }));
const descriptor = { version: 1 as const, mode: 'remote' as const, serverId: '11111111-1111-4111-8111-111111111111', profileId: 'office', contentEpoch: 'content', dataEpoch: 'data', verifiedAtMs: Date.now() };
const props = { descriptor, name: 'Office Magi', address: 'https://magi.example/api', reconnecting: false, onReconnect: vi.fn(), onChangeConnection: vi.fn() };
const cacheKey = 'magi.chat.read-cache.v1';

function save(checkedAt = Date.now()) {
  const page = {
    ...fixtures.historyPage, user_id: DEFAULT_USER_ID, session_id: 'saved-chat', revision: 'r1', not_modified: false,
    has_more: true, next_before: 'older', count: 1,
    messages: [{ ...fixtures.message, role: 'user', content: 'Remember this saved conversation', attachments: [{ attachment_id: 'photo', kind: 'image', original_name: 'photo.png', storage_path: 'https://magi.example/private/photo' }] }],
  };
  centerLocalStorage().setItem(cacheKey, JSON.stringify({ version: 1, entries: [{ key: centerStorageKey(`${cacheKey}:${DEFAULT_USER_ID}:history:saved-chat`), checkedAt, data: page }] }));
}

beforeEach(async () => {
  vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); resetChatReadMemory(); advanceBrowserContentGeneration();
  setCenterStorageScope(descriptor.serverId, descriptor.contentEpoch);
  vi.stubGlobal('fetch', vi.fn());
  await i18n.changeLanguage('en');
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('offline conversation reader', () => {
  it('lists saved history even when the session list was not cached', () => {
    save();
    expect(savedOfflineChats()).toMatchObject([{ sessionId: 'saved-chat', history: { stale: true } }]);
    render(<OfflineChatView {...props} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Offline');
    expect(screen.getAllByText('Remember this saved conversation').length).toBeGreaterThan(0);
    expect(screen.getByText(/Only the most recent saved messages/)).toBeInTheDocument();
    expect(screen.getByText(/Attachments \(available after reconnecting\): photo.png/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    Object.values(messages).forEach((mock) => expect(mock).not.toHaveBeenCalled());
  });
  it('keeps a text draft across remounts without sending it', () => {
    save(); const view = render(<OfflineChatView {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Write later' } });
    expect(screen.getByText(/Saved on this device/)).toBeInTheDocument();
    view.unmount(); render(<OfflineChatView {...props} />);
    expect(screen.getByRole('textbox')).toHaveValue('Write later');
    expect(screen.queryByRole('button', { name: /^Send$/ })).not.toBeInTheDocument();
    expect(messages.send).not.toHaveBeenCalled();
  });
  it('shows failed draft persistence instead of claiming the text is saved', () => {
    save(); render(<OfflineChatView {...props} />);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Quota exceeded'); });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unsaved draft' } });
    expect(screen.getByRole('textbox')).toHaveValue('Unsaved draft');
    expect(screen.getByText(/could not be saved to disk/)).toBeInTheDocument();
  });
  it('leaves drafts editable during reconnect but does not start a second attempt', () => {
    save(); render(<OfflineChatView {...props} reconnecting />);
    expect(screen.getByRole('button', { name: 'Reconnecting…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Choose another connection' })).toBeEnabled();
    expect(screen.getByRole('textbox')).toBeEnabled();
  });
  it('shares its conversation selection with the live application', () => {
    save();
    render(<OfflineChatView {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /Remember this saved conversation/ }));
    expect(localStorage.getItem(CHAT_SESSION_KEY(DEFAULT_USER_ID))).toBe('saved-chat');
    expect(centerLocalStorage().getItem(CHAT_SESSION_KEY(DEFAULT_USER_ID))).toBeNull();
  });
  it('does not expose expired cache or fetch missing history', () => {
    save(Date.now() - 8 * 24 * 60 * 60 * 1000);
    render(<OfflineChatView {...props} />);
    expect(screen.getByText(/No recent conversations/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(messages.getHistory).not.toHaveBeenCalled();
  });
  it('rejects a saved history whose payload belongs to another session', () => {
    save();
    const raw = centerLocalStorage().getItem(cacheKey)!;
    centerLocalStorage().setItem(cacheKey, raw.replace('"session_id":"saved-chat"', '"session_id":"other-chat"'));
    expect(savedOfflineChats()).toEqual([]);
  });
});
