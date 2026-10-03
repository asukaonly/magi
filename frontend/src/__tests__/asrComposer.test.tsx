import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useRef, useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ComposerVoiceRecorder } from '@/components/chat/ComposerVoiceRecorder';
import { APP_EVENTS } from '@/constants/events';
import type { ASRJob } from '@/api/modules/asr';

const mocks = vi.hoisted(() => ({
  status: vi.fn(), transcribe: vi.fn(), cancel: vi.fn(), start: vi.fn(),
  snapshot: { phase: 'idle', seconds: 0, audio: null as ArrayBuffer | null, error: null },
  listeners: new Set<() => void>(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/hooks/useCenterRefresh', () => ({ useCenterRefresh: vi.fn() }));
vi.mock('@/runtime/config', () => ({ subscribeRuntimeReset: () => () => undefined }));
vi.mock('@/api/modules/asr', () => ({
  asrApi: { status: mocks.status, cancel: mocks.cancel },
  createASROperation: () => ({ requestId: 'request', runtimeId: 'runtime' }),
  ownsASRScope: () => true,
  transcribeRecording: mocks.transcribe,
  asrErrorCode: () => 'request_failed',
}));
vi.mock('@/hooks/useAudioIO', async () => {
  const { useSyncExternalStore } = await import('react');
  const set = (phase: string, audio: ArrayBuffer | null = null) => {
    mocks.snapshot = { ...mocks.snapshot, phase, audio }; mocks.listeners.forEach(listener => listener());
  };
  const recorder = { start: async () => { mocks.start(); set('recording'); },
    stop: async () => { set('ready', new ArrayBuffer(64)); }, cancel: () => set('cancelled') };
  return { useAudioIO: () => ({ recorder,
    recording: useSyncExternalStore(listener => { mocks.listeners.add(listener); return () => { mocks.listeners.delete(listener); }; }, () => mocks.snapshot) }) };
});
function Harness({ scope = 'one', disabled = false }: { scope?: string; disabled?: boolean }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [draft, setDraft] = useState('hello world');
  return <><textarea ref={ref} aria-label="draft" value={draft} onChange={event => setDraft(event.target.value)} />
    <ComposerVoiceRecorder scopeKey={scope} draft={draft} textareaRef={ref} onInsert={setDraft} disabled={disabled} /></>;
}
let resolve: (job: ASRJob) => void;
const result = (): ASRJob => ({ request_id: 'request', runtime_id: 'runtime', state: 'succeeded', error: null, expires_at: 1,
  result: { text: '世界', language: null, no_speech: false, engine: 'local', model: 'test' } });
beforeEach(() => {
  vi.clearAllMocks(); mocks.listeners.clear(); mocks.snapshot = { phase: 'idle', seconds: 0, audio: null, error: null };
  mocks.status.mockResolvedValue({ ready: true, runtime_id: 'runtime' }); mocks.cancel.mockResolvedValue(undefined);
  mocks.transcribe.mockImplementation(() => new Promise<ASRJob>(yes => { resolve = yes; }));
});
afterEach(cleanup);
async function record() {
  await act(async () => undefined);
  fireEvent.click(screen.getByRole('button', { name: 'asr.record' }));
  await waitFor(() => expect(mocks.start).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole('button', { name: 'asr.stop' }));
  await waitFor(() => expect(mocks.transcribe).toHaveBeenCalledOnce());
}
it('inserts into the original selection without sending', async () => {
  render(<Harness />);
  const draft = screen.getByRole('textbox') as HTMLTextAreaElement;
  draft.setSelectionRange(6, 11);
  await record();
  await act(async () => resolve(result()));
  expect(draft.value).toBe('hello 世界');
  expect(mocks.cancel).toHaveBeenCalled();
});
it('preserves edits and requires explicit insertion', async () => {
  render(<Harness />); await record();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'new draft' } });
  await act(async () => resolve(result()));
  expect(screen.getByRole('textbox')).toHaveValue('new draft');
  expect(screen.getByText('asr.draftChanged')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'asr.insert' }));
  expect(screen.getByRole('textbox')).toHaveValue('new draft世界');
});
it('detects an edit followed by undo to the same text', async () => {
  render(<Harness />); await record();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'changed' } });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hello world' } });
  await act(async () => resolve(result()));
  expect(screen.getByText('asr.draftChanged')).toBeInTheDocument();
});
it.each(['scope', 'disabled', 'cancel', 'clear', 'history', 'send'] as const)('discards late results after %s', async reason => {
  const view = render(<Harness />); await record();
  if (reason === 'scope') view.rerender(<Harness scope="two" />);
  if (reason === 'disabled') view.rerender(<Harness disabled />);
  if (reason === 'cancel') fireEvent.click(screen.getByRole('button', { name: 'asr.cancel' }));
  if (reason === 'clear') act(() => window.dispatchEvent(new Event(APP_EVENTS.MEMORY_CLEAR_STARTED)));
  if (reason === 'history') act(() => window.dispatchEvent(new Event(APP_EVENTS.CHAT_HISTORY_CLEARED)));
  if (reason === 'send') fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  await act(async () => resolve(result()));
  expect(screen.getByRole('textbox')).toHaveValue('hello world');
  expect(screen.queryByText('asr.draftChanged')).not.toBeInTheDocument();
  expect(mocks.cancel).toHaveBeenCalled();
});
it('keeps a result in preview while an IME composition is active', async () => {
  render(<Harness />); await record();
  fireEvent.compositionStart(screen.getByRole('textbox'));
  await act(async () => resolve(result()));
  expect(screen.getByRole('textbox')).toHaveValue('hello world');
  expect(screen.getByText('asr.draftChanged')).toBeInTheDocument();
});
it('does not request microphone access before ASR is configured', async () => {
  mocks.status.mockResolvedValue({ ready: false }); render(<Harness />);
  await act(async () => undefined);
  fireEvent.click(screen.getByRole('button', { name: 'asr.record' }));
  expect(mocks.start).not.toHaveBeenCalled();
});

it('does not cancel recognition when Enter confirms an active IME composition', async () => {
  render(<Harness />); await record();
  fireEvent.compositionStart(screen.getByRole('textbox'));
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', isComposing: false });
  expect(mocks.cancel).not.toHaveBeenCalled();
  await act(async () => resolve(result()));
  expect(screen.getByText('asr.draftChanged')).toBeInTheDocument();
});
