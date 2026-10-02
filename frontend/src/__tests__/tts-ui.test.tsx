import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { TTSChatProvider, ReadMessageButton } from '@/components/chat/TTSChatProvider';
import { TTSSettings } from '@/components/settings/TTSSettings';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import type { RealtimeMessage } from '@/realtime/provider';

const mock = vi.hoisted(() => ({
  speak: vi.fn(async (_source: unknown, _messageId?: string, _mode?: string) => undefined), stop: vi.fn(), pause: vi.fn(async () => undefined),
  canAutoplay: vi.fn(() => true), listeners: new Set<(message: RealtimeMessage) => void>(),
  settings: vi.fn(), save: vi.fn(), model: vi.fn(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/hooks/useTTS', () => ({ useTTS: () => ({ controller: mock, state: { phase: 'idle', error: null, cancellation: 'none' } }) }));
vi.mock('@/lib/audio/tts-controller', () => ({ messageSource: async (session_id: string, message_id: string) => ({ kind: 'message', session_id, message_id, revision: 'a'.repeat(64) }) }));
vi.mock('@/runtime/config', () => ({ subscribeRuntimeReconnect: () => () => undefined, subscribeRuntimeReset: () => () => undefined }));
vi.mock('@/realtime/provider', () => ({ useRealtime: () => ({ subscribe: (listener: (message: RealtimeMessage) => void) => { mock.listeners.add(listener); return () => mock.listeners.delete(listener); } }) }));
vi.mock('@/api/event-contract', () => ({ parseChatMessage: (message: unknown) => message }));
vi.mock('@/api/modules/tts', () => ({ ttsApi: mock }));

const message: ChatTimelineMessage = { id: 'm1', messageId: 'm1', role: 'assistant', kind: 'assistant', messageKind: 'assistant_final', content: 'Hello', timestamp: Date.now(), turnId: 'turn' };
const emit = (overrides = {}) => act(() => mock.listeners.forEach((listener) => listener({ event: 'chat_message_upserted', data: {
  session_id: 's1', message: { role: 'assistant', kind: 'assistant', message_kind: 'assistant_final', message_id: 'm1', turn_id: 'turn', content: 'Hello', timestamp: Date.now() + 10, ...overrides },
} })));
beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); mock.listeners.clear(); mock.canAutoplay.mockReturnValue(true); });

it('defaults auto-read off and reads a message only on explicit action', async () => {
  render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }}><ReadMessageButton message={message} /></TTSChatProvider>);
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  emit(); expect(mock.speak).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'tts.read' }));
  expect(mock.speak).toHaveBeenCalledOnce();
  expect(await mock.speak.mock.calls[0][0]).toMatchObject({ kind: 'message', session_id: 's1', message_id: 'm1' });
});

it('never reads history, foreign turns, duplicates or replay after a disconnect', () => {
  localStorage.setItem('magi.tts.auto.v1', 'true');
  render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }} />);
  expect(mock.speak).not.toHaveBeenCalled();
  emit({ turn_id: 'foreign' }); expect(mock.speak).not.toHaveBeenCalled();
  emit(); emit(); expect(mock.speak).toHaveBeenCalledOnce();
  act(() => mock.listeners.forEach((listener) => listener({ event: 'connection_interrupted' })));
  emit({ message_id: 'late' }); expect(mock.speak).toHaveBeenCalledOnce();
  expect(mock.stop).toHaveBeenCalled();
});

it('stops a revised or removed message without automatically reading the revision', () => {
  localStorage.setItem('magi.tts.auto.v1', 'true');
  const view = render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }} />);
  emit(); emit({ content: 'Changed' });
  expect(mock.speak).toHaveBeenCalledOnce();
  expect(mock.stop).toHaveBeenCalled();
  view.rerender(<TTSChatProvider sessionId="s1" messages={[]} submittedTurns={{}} />);
  expect(mock.stop).toHaveBeenCalledTimes(2);
});

it('does not auto-read during manual playback and does not later backfill the skipped event', () => {
  localStorage.setItem('magi.tts.auto.v1', 'true');
  mock.canAutoplay.mockReturnValue(false);
  render(<TTSChatProvider sessionId="s1" messages={[]} submittedTurns={{ s1: 'turn' }} />);
  emit(); mock.canAutoplay.mockReturnValue(true); emit();
  expect(mock.speak).not.toHaveBeenCalled();
});

it('previews saved settings and disables preview while a selection is unsaved', async () => {
  mock.settings.mockResolvedValue({ settings: { engine: 'local', local_model: 'kokoro-multi-lang-v1_0', local_voice: 'zf_xiaobei', local_speed: 1, provider_id: null }, revision: 'rev', local_voices: [{ id: 'zf_xiaobei', language: 'zh' }], voices: [], model: { state: 'ready', runtime_available: true, progress: 1 } });
  render(<TTSSettings providers={{}} />);
  const preview = await screen.findByRole('button', { name: 'tts.preview' });
  fireEvent.click(preview); expect(mock.speak).toHaveBeenCalledWith({ kind: 'text', text: 'tts.sample' });
  fireEvent.change(screen.getByLabelText('tts.speed'), { target: { value: '1.2' } });
  await waitFor(() => expect(preview).toBeDisabled());
});
