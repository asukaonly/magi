import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { TTSChatProvider, ReadMessageButton } from '@/components/chat/TTSChatProvider';
import { TTSSettings } from '@/components/settings/TTSSettings';
import { SettingsVoiceSection } from '@/components/settings/SettingsVoiceSection';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import type { RealtimeMessage } from '@/realtime/provider';
import type { SpeechSnapshot } from '@/lib/audio/tts-controller';

const mock = vi.hoisted(() => ({
  speak: vi.fn(async (_source: unknown, _messageId?: string, _mode?: string) => undefined), stop: vi.fn(), pause: vi.fn(async () => undefined),
  canAutoplay: vi.fn(() => true), listeners: new Set<(message: RealtimeMessage) => void>(),
  settings: vi.fn(), save: vi.fn(), model: vi.fn(),
  state: { phase: 'idle', error: null, cancellation: 'none', messageId: null, acceptedSegments: 0 } as SpeechSnapshot,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/hooks/useTTS', () => ({ useTTS: () => ({ controller: mock, state: mock.state }) }));
vi.mock('@/lib/audio/tts-controller', () => ({ messageSource: async (session_id: string, message_id: string) => ({ kind: 'message', session_id, message_id, revision: 'a'.repeat(64) }) }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => ({ mode: 'local', apiBaseUrl: 'http://localhost:8000' }), getRuntimeGeneration: () => 0, subscribeRuntimeReconnect: () => () => undefined, subscribeRuntimeReset: () => () => undefined }));
vi.mock('@/realtime/provider', () => ({ useRealtime: () => ({ subscribe: (listener: (message: RealtimeMessage) => void) => { mock.listeners.add(listener); return () => mock.listeners.delete(listener); } }) }));
vi.mock('@/api/event-contract', () => ({ parseChatMessage: (message: unknown) => message }));
vi.mock('@/api/modules/tts', () => ({ ttsApi: mock }));

const message: ChatTimelineMessage = { id: 'm1', messageId: 'm1', role: 'assistant', kind: 'assistant', messageKind: 'assistant_final', content: 'Hello', timestamp: Date.now(), turnId: 'turn' };
const emit = (overrides = {}) => act(() => mock.listeners.forEach((listener) => listener({ event: 'chat_message_upserted', data: {
  session_id: 's1', message: { role: 'assistant', kind: 'assistant', message_kind: 'assistant_final', message_id: 'm1', turn_id: 'turn', content: 'Hello', timestamp: Date.now() + 10, ...overrides },
} })));
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks(); mock.listeners.clear(); mock.canAutoplay.mockReturnValue(true);
  mock.state = { phase: 'idle', error: null, cancellation: 'none', messageId: null, acceptedSegments: 0 };
  mock.settings.mockResolvedValue({ settings: { engine: 'local', local_model: 'kokoro-multi-lang-v1_0', local_voice: 'zf_xiaobei', local_speed: 1, provider_id: null }, revision: 'rev', local_voices: [{ id: 'zf_xiaobei', language: 'zh' }], voices: [], model: { state: 'ready', runtime_available: true, progress: 1 } });
});

it('defaults auto-read off and reads a message only on explicit action', async () => {
  render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }}><ReadMessageButton message={message} /></TTSChatProvider>);
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
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

it('previews a draft without changing the saved configuration', async () => {
  mock.settings.mockResolvedValue({ settings: { engine: 'local', local_model: 'kokoro-multi-lang-v1_0', local_voice: 'zf_xiaobei', local_speed: 1, provider_id: null }, revision: 'rev', local_voices: [{ id: 'zf_xiaobei', language: 'zh' }], voices: [], model: { state: 'ready', runtime_available: true, progress: 1 } });
  render(<TTSSettings providers={{}} onConfigureProviders={vi.fn()} />);
  const preview = await screen.findByRole('button', { name: 'tts.preview' });
  expect(screen.queryByRole('switch', { name: 'tts.automatic' })).not.toBeInTheDocument();
  fireEvent.click(preview); expect(mock.speak).toHaveBeenCalledWith({ kind: 'text', text: 'tts.sample' }, null, 'manual', expect.objectContaining({ local_speed: 1 }));
  fireEvent.change(screen.getByLabelText('tts.speed'), { target: { value: '1.2' } });
  mock.speak.mockClear();
  fireEvent.click(preview);
  expect(mock.save).not.toHaveBeenCalled();
  expect(mock.speak).toHaveBeenCalledWith({ kind: 'text', text: 'tts.sample' }, null, 'manual', expect.objectContaining({ local_speed: 1.2 }));
  expect(screen.getByRole('button', { name: 'tts.save' })).toBeEnabled();
});

it('keeps preview unavailable while the local runtime or model is missing', async () => {
  mock.settings.mockResolvedValue({ settings: { engine: 'local', local_model: 'kokoro-multi-lang-v1_0', local_voice: 'zf_xiaobei', local_speed: 1, provider_id: null }, revision: 'rev', local_voices: [], model: { state: 'missing', runtime_available: false, progress: 0 } });
  render(<TTSSettings providers={{}} onConfigureProviders={vi.fn()} />);
  const preview = await screen.findByRole('button', { name: 'tts.preview' });
  expect(preview).toBeDisabled();
  expect(screen.getByText('tts.errors.runtime_missing')).toBeInTheDocument();
  fireEvent.click(preview);
  expect(mock.speak).not.toHaveBeenCalled();
});

it('uses the shared engine selector and exposes provider configuration for remote speech', async () => {
  const user = userEvent.setup();
  const configure = vi.fn();
  mock.settings.mockResolvedValue({ settings: { engine: 'local', local_model: 'kokoro-multi-lang-v1_0', local_voice: 'zf_xiaobei', local_speed: 1, provider_id: null }, revision: 'rev', local_voices: [], model: { state: 'ready', runtime_available: true, progress: 1 } });
  render(<TTSSettings providers={{}} onConfigureProviders={configure} />);
  await user.click(await screen.findByRole('button', { name: 'tts.engine' }));
  await user.click(screen.getByRole('button', { name: 'tts.remote' }));
  expect(screen.queryByText('Kokoro')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'tts.preview' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'asr.addProvider' }));
  expect(configure).toHaveBeenCalledOnce();
});


it('saves auto-read in settings immediately and updates the mounted chat independently of model drafts', async () => {
  const view = render(<>
    <TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }} />
    <TTSSettings providers={{}} onConfigureProviders={vi.fn()} />
    <SettingsVoiceSection draftConfig={structuredClone(DEFAULT_SYSTEM_CONFIG)} patchDraftConfig={vi.fn()} onConfigureModel={vi.fn()} />
  </>);
  await screen.findByRole('button', { name: 'tts.preview' });
  const toggle = screen.getByRole('switch', { name: 'tts.automatic' });
  expect(toggle).toHaveAttribute('aria-checked', 'false');
  fireEvent.change(screen.getByLabelText('tts.speed'), { target: { value: '1.2' } });
  emit(); expect(mock.speak).not.toHaveBeenCalled();
  fireEvent.click(toggle);
  expect(localStorage.getItem('magi.tts.auto.v1')).toBe('true');
  expect(mock.speak).not.toHaveBeenCalled();
  emit(); expect(mock.speak).toHaveBeenCalledWith(expect.anything(), 'm1', 'auto');
  fireEvent.click(toggle);
  expect(localStorage.getItem('magi.tts.auto.v1')).toBe('false');
  expect(mock.stop).toHaveBeenCalledTimes(2);
  emit({ message_id: 'm2' }); expect(mock.speak).toHaveBeenCalledOnce();
  expect(screen.getByLabelText('tts.speed')).toHaveValue(1.2);
  expect(mock.save).not.toHaveBeenCalled();
  view.unmount();
  render(<SettingsVoiceSection draftConfig={structuredClone(DEFAULT_SYSTEM_CONFIG)} patchDraftConfig={vi.fn()} onConfigureModel={vi.fn()} />);
  expect(screen.getByRole('switch', { name: 'tts.automatic' })).toHaveAttribute('aria-checked', 'false');
});

it('keeps auto-read unchanged and reports failure if the device preference cannot be saved', async () => {
  localStorage.setItem('magi.tts.auto.v1', 'true');
  render(<>
    <TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }} />
    <TTSSettings providers={{}} onConfigureProviders={vi.fn()} />
    <SettingsVoiceSection draftConfig={structuredClone(DEFAULT_SYSTEM_CONFIG)} patchDraftConfig={vi.fn()} onConfigureModel={vi.fn()} />
  </>);
  await screen.findByRole('button', { name: 'tts.preview' });
  const persist = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage unavailable'); });
  try {
    fireEvent.click(screen.getByRole('switch', { name: 'tts.automatic' }));
    expect(screen.getByRole('alert')).toHaveTextContent('tts.preferenceSaveFailed');
    expect(screen.getByRole('switch', { name: 'tts.automatic' })).toHaveAttribute('aria-checked', 'true');
    expect(mock.stop).not.toHaveBeenCalled();
    emit(); expect(mock.speak).toHaveBeenCalledOnce();
  } finally {
    persist.mockRestore();
  }
  fireEvent.click(screen.getByRole('switch', { name: 'tts.automatic' }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('switch', { name: 'tts.automatic' })).toHaveAttribute('aria-checked', 'false');
});

it('shows chat playback controls only during speech and hides them after completion', () => {
  mock.state.phase = 'generating';
  const view = render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.getByRole('status')).toHaveTextContent('tts.phase.generating');
  mock.state.phase = 'playing';
  view.rerender(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  fireEvent.click(screen.getByRole('button', { name: 'tts.pause' }));
  expect(mock.pause).toHaveBeenCalledOnce();
  mock.state.phase = 'paused';
  view.rerender(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.getByRole('button', { name: 'tts.resume' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'tts.stop' })).toBeInTheDocument();
  mock.state.phase = 'completed';
  view.rerender(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('keeps cancellation uncertainty visible until stopping is confirmed', () => {
  mock.state.phase = 'playing';
  const view = render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  fireEvent.click(screen.getByRole('button', { name: 'tts.stop' }));
  expect(mock.stop).toHaveBeenCalledOnce();
  mock.state.phase = 'stopped'; mock.state.cancellation = 'pending';
  view.rerender(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.getByText('tts.cancelling')).toBeInTheDocument();
  mock.state.cancellation = 'unknown';
  view.rerender(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.getByRole('alert')).toHaveTextContent('tts.cancelUnknown');
  mock.state.cancellation = 'confirmed';
  view.rerender(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('keeps synthesis failures visible in the chat', () => {
  mock.state.phase = 'failed'; mock.state.error = 'runtime_missing';
  render(<TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{}} />);
  expect(screen.getByRole('alert')).toHaveTextContent('tts.errors.runtime_missing');
});


it('keeps the edited settings and preview available if saving fails', async () => {
  mock.save.mockRejectedValueOnce(new Error('Connection failed'));
  render(<TTSSettings providers={{}} onConfigureProviders={vi.fn()} />);
  await screen.findByRole('button', { name: 'tts.preview' });
  fireEvent.change(screen.getByLabelText('tts.speed'), { target: { value: '1.2' } });
  fireEvent.click(screen.getByRole('button', { name: 'tts.save' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('tts.settingsFailed');
  expect(mock.speak).not.toHaveBeenCalled();
  expect(screen.getByLabelText('tts.speed')).toHaveValue(1.2);
  expect(screen.getByRole('button', { name: 'tts.preview' })).toBeEnabled();
});

it('does not start a late preview after leaving the page during save', async () => {
  let completeSave: (value: unknown) => void = () => {};
  mock.save.mockImplementationOnce(() => new Promise(resolve => { completeSave = resolve; }));
  const view = render(<TTSSettings providers={{}} onConfigureProviders={vi.fn()} />);
  await screen.findByRole('button', { name: 'tts.preview' });
  fireEvent.change(screen.getByLabelText('tts.speed'), { target: { value: '1.2' } });
  fireEvent.click(screen.getByRole('button', { name: 'tts.save' }));
  view.unmount();
  await act(async () => completeSave(await mock.settings()));
  expect(mock.speak).not.toHaveBeenCalled();
});

it.each(['completed', 'stopped'] as const)('hides settled %s playback in settings', async (phase) => {
  mock.state.phase = phase;
  mock.state.cancellation = 'confirmed';
  render(<TTSSettings providers={{}} onConfigureProviders={vi.fn()} />);
  await screen.findByRole('button', { name: 'tts.preview' });
  expect(screen.queryByText(`tts.phase.${phase}`)).not.toBeInTheDocument();
});
