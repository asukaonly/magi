import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { TTSChatProvider, ReadMessageButton } from '@/components/chat/TTSChatProvider';
import { ttsConfiguration, modernTTSConfiguration } from './fixtures/tts';
import { TTSSettings } from '@/components/settings/TTSSettings';
import type { TTSModelStatus } from '@/api/modules/tts';
import { SettingsVoiceSection } from '@/components/settings/SettingsVoiceSection';
import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import type { RealtimeMessage } from '@/realtime/provider';
import type { SpeechSnapshot } from '@/lib/audio/tts-controller';

const mock = vi.hoisted(() => ({
  speak: vi.fn(async (_source: unknown, _messageId?: string, _mode?: string) => undefined), stop: vi.fn(), pause: vi.fn(async () => undefined),
  canAutoplay: vi.fn(() => true), listeners: new Set<(message: RealtimeMessage) => void>(),
  settings: vi.fn(), save: vi.fn(), model: vi.fn(), cancelDownload: vi.fn(), inspectDirectory: vi.fn(), uploadReference: vi.fn(), deleteReference: vi.fn(),
  state: { phase: 'idle', error: null, cancellation: 'none', messageId: null, acceptedSegments: 0 } as SpeechSnapshot,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
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
  mock.settings.mockResolvedValue(ttsConfiguration());
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
  mock.settings.mockResolvedValue(ttsConfiguration());
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
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
  mock.settings.mockResolvedValue(ttsConfiguration('missing', false));
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  const preview = await screen.findByRole('button', { name: 'tts.preview' });
  expect(preview).toBeDisabled();
  expect(screen.getByText('tts.errors.runtime_missing')).toBeInTheDocument();
  fireEvent.click(preview);
  expect(mock.speak).not.toHaveBeenCalled();
});

it('selects models directly and explains how to add an online connection', async () => {
  const user = userEvent.setup();
  const configure = vi.fn();
  mock.settings.mockResolvedValue(ttsConfiguration());
  render(<TTSSettings onConfigureProviders={configure} />);
  await screen.findByRole('button', { name: 'tts.model' });
  expect(screen.queryByRole('button', { name: 'tts.engine' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'tts.connectService' }));
  expect(configure).toHaveBeenCalledOnce();
});


it('saves auto-read in settings immediately and updates the mounted chat independently of model drafts', async () => {
  const view = render(<>
    <TTSChatProvider sessionId="s1" messages={[message]} submittedTurns={{ s1: 'turn' }} />
    <TTSSettings onConfigureProviders={vi.fn()} />
    <SettingsVoiceSection draftConfig={structuredClone(DEFAULT_SYSTEM_CONFIG)} patchDraftConfig={vi.fn()} onConfigureModel={vi.fn()} />
  </>);
  await screen.findByRole('button', { name: 'tts.preview' });
  const toggle = screen.getByRole('switch', { name: 'tts.automatic' });
  expect(toggle).toHaveAttribute('aria-checked', 'false');
  fireEvent.change(screen.getByLabelText('tts.speed'), { target: { value: '1.2' } });
  mock.stop.mockClear();
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
    <TTSSettings onConfigureProviders={vi.fn()} />
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
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
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
  const view = render(<TTSSettings onConfigureProviders={vi.fn()} />);
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
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  await screen.findByRole('button', { name: 'tts.preview' });
  expect(screen.queryByText(`tts.phase.${phase}`)).not.toBeInTheDocument();
});

it('switches to Melo with its single voice and resets incompatible choices without saving', async () => {
  const user = userEvent.setup();
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  await user.click(await screen.findByRole('button', { name: 'tts.model' }));
  await user.click(screen.getByRole('button', { name: 'MeloTTS · tts.local' }));
  expect(screen.queryByRole('button', { name: 'tts.voice' })).not.toBeInTheDocument();
  expect(screen.getByText('tts.meloVoice')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'tts.preview' }));
  expect(mock.speak).toHaveBeenCalledWith(expect.anything(), null, 'manual', expect.objectContaining({
    local_model: 'vits-melo-tts-zh_en', local_voice: 'zh_en', local_speed: 1,
  }));
  expect(mock.save).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'tts.model' }));
  await user.click(screen.getByRole('button', { name: 'Kokoro · tts.local' }));
  expect(screen.getByRole('button', { name: 'tts.voice' })).toBeInTheDocument();
});

it('shows only supported remote controls and previews against the selected service', async () => {
  const config = ttsConfiguration();
  config.models.push({ ...config.models[0], engine: 'remote', model_id: 'qwen3-tts-instruct-flash',
    name: 'Qwen3 Instruct', provider_id: 'speech', provider_name: 'Bailian', status: null,
    voices: [{ id: 'Cherry', language: 'zh', name: 'Cherry' }], custom_voice: true,
    speed_min: null, speed_max: null, instructions: true });
  mock.settings.mockResolvedValue(config);
  const user = userEvent.setup();
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText('tts.speed'), { target: { value: '1.4' } });
  await user.click(screen.getByRole('button', { name: 'tts.model' }));
  await user.click(screen.getByRole('button', { name: 'Qwen3 Instruct · Bailian' }));
  expect(screen.queryByLabelText('tts.speed')).not.toBeInTheDocument();
  expect(screen.getByText('tts.previewRemote')).toBeInTheDocument();
  await user.click(screen.getByText('tts.expression'));
  fireEvent.change(screen.getByLabelText('tts.instructions'), { target: { value: 'Speak calmly.' } });
  fireEvent.click(screen.getByRole('button', { name: 'tts.preview' }));
  expect(mock.speak).toHaveBeenCalledWith(expect.anything(), null, 'manual', expect.objectContaining({
    engine: 'remote', provider_id: 'speech', remote_model: 'qwen3-tts-instruct-flash',
    remote_voice: 'Cherry', remote_speed: 1, instructions: 'Speak calmly.',
  }));
  await user.click(screen.getByRole('button', { name: 'tts.voice' }));
  await user.click(screen.getByRole('button', { name: 'tts.customVoice' }));
  expect(screen.getByRole('button', { name: 'tts.preview' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/tts.voiceId/), { target: { value: 'provider-voice' } });
  expect(screen.getByRole('button', { name: 'tts.preview' })).toBeEnabled();
  expect(mock.save).not.toHaveBeenCalled();
});

it('retains the selected model progress and rejects a stale poll after cancellation', async () => {
  const config = ttsConfiguration();
  config.settings.local_model = 'vits-melo-tts-zh_en';
  config.settings.local_voice = 'zh_en';
  const downloading: TTSModelStatus = {
    model_id: 'vits-melo-tts-zh_en', state: 'downloading', error: null, runtime_available: true, recommended: false,
    download: { phase: 'downloading', downloaded_bytes: 50, total_bytes: 100, speed_bps: 10, eta_seconds: 5, files_completed: 0, total_files: 4 },
  };
  config.models[1].status = downloading;
  mock.settings.mockResolvedValue(config);
  let completePoll!: (value: TTSModelStatus) => void;
  mock.model.mockImplementationOnce(() => new Promise(resolve => { completePoll = resolve; }));
  mock.cancelDownload.mockResolvedValue({ ...downloading, state: 'cancelled', download: { ...downloading.download!, phase: 'cancelled', speed_bps: 0, eta_seconds: null } });
  const view = render(<TTSSettings onConfigureProviders={vi.fn()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'tts.cancelDownload' }));
  await screen.findByRole('button', { name: 'modelDownload.resume' });
  expect(mock.cancelDownload).toHaveBeenCalledWith('vits-melo-tts-zh_en');
  await act(async () => { completePoll(downloading); });
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
  expect(screen.getByText('modelDownload.phases.cancelled')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'tts.cancelDownload' })).not.toBeInTheDocument();
  view.unmount();
});

it('defaults to the recommended model and groups more models separately', async () => {
  mock.settings.mockResolvedValue(modernTTSConfiguration());
  const user = userEvent.setup();
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  const model = await screen.findByRole('button', { name: 'tts.model' });
  expect(model).toHaveTextContent('VoxCPM2');
  expect(screen.queryByLabelText('tts.speed')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('tts.voiceId')).not.toBeInTheDocument();
  expect(screen.getByLabelText(/tts.voiceDescription/)).toBeInTheDocument();
  await user.click(model);
  expect(screen.getByText('tts.recommendedModels')).toBeInTheDocument();
  expect(screen.getByText('tts.moreModels')).toBeInTheDocument();
});

it('requires a reference only for models that need it and clears incompatible voice options', async () => {
  const config = modernTTSConfiguration();
  mock.settings.mockResolvedValue(config);
  mock.uploadReference.mockResolvedValue({ id: 'a'.repeat(64), name: 'voice.wav', seconds: 4 });
  const user = userEvent.setup();
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  const preview = await screen.findByRole('button', { name: 'tts.preview' });
  expect(preview).toBeEnabled();
  fireEvent.change(screen.getByLabelText(/tts.voiceDescription/), { target: { value: 'A calm voice' } });
  await user.click(screen.getByRole('button', { name: 'tts.model' }));
  await user.click(screen.getByRole('button', { name: 'MOSS Nano · tts.local' }));
  expect(preview).toBeDisabled();
  expect(screen.queryByLabelText(/tts.voiceDescription/)).not.toBeInTheDocument();
  await user.upload(screen.getByLabelText('tts.uploadReference'), new File(['wav fixture'], 'voice.wav', { type: 'audio/wav' }));
  expect(preview).toBeEnabled();
  fireEvent.click(preview);
  expect(mock.speak).toHaveBeenCalledWith(expect.anything(), null, 'manual', expect.objectContaining({
    local_model: 'moss-tts-nano', reference_audio: 'a'.repeat(64), voice_description: '',
  }));
});

it('saves voice recipes only with page settings and keeps them scoped to their model', async () => {
  const config = modernTTSConfiguration();
  mock.settings.mockResolvedValue(config);
  mock.save.mockResolvedValue(config);
  const user = userEvent.setup();
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText(/tts.voiceDescription/), { target: { value: 'Calm and clear' } });
  await user.click(screen.getByText('tts.voicePresets'));
  fireEvent.change(screen.getByLabelText('tts.presetName'), { target: { value: 'Reading' } });
  await user.click(screen.getByRole('button', { name: 'tts.addPreset' }));
  expect(mock.save).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'tts.savedVoice' })).toHaveTextContent('Reading');
  await user.click(screen.getByRole('button', { name: 'tts.model' }));
  await user.click(screen.getByRole('button', { name: 'MeloTTS · tts.local' }));
  expect(screen.queryByRole('button', { name: 'tts.savedVoice' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'tts.save' }));
  expect(mock.save).toHaveBeenCalledWith(expect.objectContaining({ voice_presets: [expect.objectContaining({
    model_id: 'voxcpm2-8bit', name: 'Reading', description: 'Calm and clear',
  })] }), 'rev');
});

it('verifies an external directory before preview and never exposes managed deletion for it', async () => {
  const config = modernTTSConfiguration();
  mock.settings.mockResolvedValue(config);
  mock.inspectDirectory.mockResolvedValue(config.models[0].status);
  const user = userEvent.setup();
  render(<TTSSettings onConfigureProviders={vi.fn()} />);
  const preview = await screen.findByRole('button', { name: 'tts.preview' });
  await user.click(screen.getByText('tts.useDirectory'));
  fireEvent.change(screen.getByLabelText('tts.modelDirectory'), { target: { value: '/models/vox' } });
  expect(preview).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'tts.deleteModel' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'tts.validateDirectory' }));
  expect(mock.inspectDirectory).toHaveBeenCalledWith({ model_id: 'voxcpm2-8bit', path: '/models/vox', codec_path: '' });
  expect(preview).toBeEnabled();
  fireEvent.change(screen.getByLabelText('tts.modelDirectory'), { target: { value: '/models/another' } });
  expect(preview).toBeDisabled();
});
