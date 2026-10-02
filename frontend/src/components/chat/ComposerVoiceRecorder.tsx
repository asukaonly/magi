import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { Mic, Square, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { asrApi, asrErrorCode, createASROperation, ownsASRScope, transcribeRecording, type ASROperation, type ASRStatus } from '@/api/modules/asr';
import { useAudioIO } from '@/hooks/useAudioIO';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { subscribeRuntimeReset } from '@/runtime/config';
import { useChatShellStore } from '@/stores/chat-shell';
import { APP_EVENTS } from '@/constants/events';

interface Props {
  scopeKey: string;
  draft: string;
  textareaRef: RefObject<HTMLTextAreaElement>;
  onInsert: (draft: string) => void;
  disabled: boolean;
}
type Capture = {
  operation: ASROperation; abort: AbortController; scope: string; revision: number;
  draft: string; start: number; end: number; submitted: boolean;
};
export interface ComposerVoiceRecorderHandle { cancel: () => void }
export const ComposerVoiceRecorder = forwardRef<ComposerVoiceRecorderHandle, Props>(function ComposerVoiceRecorder({ scopeKey, draft, textareaRef, onInsert, disabled }, ref) {
  const { t } = useTranslation('app');
  const { recorder, recording } = useAudioIO(scopeKey);
  const [status, setStatus] = useState<ASRStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recognizing, setRecognizing] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const active = useRef<Capture | null>(null);
  const latest = useRef({ draft, scopeKey, disabled, onInsert, revision: 0 });
  const composing = useRef(false);
  const mounted = useRef(true);
  useLayoutEffect(() => {
    const revision = latest.current.revision + (latest.current.draft === draft ? 0 : 1);
    latest.current = { draft, scopeKey, disabled, onInsert, revision };
  }, [draft, scopeKey, disabled, onInsert]);

  const cancel = useCallback(() => {
    const capture = active.current;
    active.current = null;
    capture?.abort.abort();
    recorder.cancel();
    if (capture?.submitted) void asrApi.cancel(capture.operation).catch(() => undefined);
    if (mounted.current) { setRecognizing(false); setPreview(null); }
  }, [recorder]);
  useImperativeHandle(ref, () => ({ cancel }), [cancel]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; cancel(); };
  }, [cancel]);
  useEffect(() => { cancel(); }, [scopeKey, disabled, cancel]);
  useEffect(() => {
    const reset = subscribeRuntimeReset(cancel);
    const events = [APP_EVENTS.MEMORY_CLEAR_STARTED, APP_EVENTS.CHAT_HISTORY_CLEARED, APP_EVENTS.CHAT_SESSION_DELETED, APP_EVENTS.CENTER_MAINTENANCE];
    for (const event of events) window.addEventListener(event, cancel);
    return () => { reset(); for (const event of events) window.removeEventListener(event, cancel); };
  }, [cancel]);
  const refresh = useCallback(async () => {
    try { const value = await asrApi.status(); if (mounted.current) setStatus(value); }
    catch { if (mounted.current) setStatus(null); }
  }, []);
  useCenterRefresh(refresh, ['config']);
  useEffect(() => {
    const abort = new AbortController();
    void asrApi.status(abort.signal).then(value => { if (!abort.signal.aborted) setStatus(value); })
      .catch(() => undefined);
    return () => abort.abort();
  }, [scopeKey]);
  useEffect(() => {
    const area = textareaRef.current;
    if (!area) return;
    const start = () => { composing.current = true; };
    const end = () => { composing.current = false; };
    // Stop before an Enter submission, including fast replies completed in one render.
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) cancel();
    };
    area.addEventListener('compositionstart', start);
    area.addEventListener('compositionend', end);
    area.addEventListener('keydown', key, true);
    return () => {
      area.removeEventListener('compositionstart', start);
      area.removeEventListener('compositionend', end);
      area.removeEventListener('keydown', key, true);
    };
  }, [textareaRef, cancel]);

  useEffect(() => {
    const capture = active.current;
    if (recording.phase !== 'ready' || !recording.audio || !capture || capture.submitted) return;
    capture.submitted = true;
    const audio = recording.audio;
    recorder.cancel();
    setRecognizing(true);
    const current = () => mounted.current && active.current === capture && !capture.abort.signal.aborted
      && ownsASRScope(capture.operation) && latest.current.scopeKey === capture.scope && !latest.current.disabled;
    void transcribeRecording(capture.operation, audio, capture.abort.signal).then(job => {
      if (!current()) return;
      if (job.state !== 'succeeded' || !job.result) { setError(job.error ?? 'request_failed'); return; }
      const text = job.result.text;
      if (job.result.no_speech || !text) { setError('no_speech'); return; }
      if (latest.current.revision !== capture.revision || composing.current) { setPreview(text); return; }
      const next = capture.draft.slice(0, capture.start) + text + capture.draft.slice(capture.end);
      latest.current.onInsert(next);
      window.requestAnimationFrame(() => {
        if (!mounted.current || latest.current.scopeKey !== capture.scope) return;
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(capture.start + text.length, capture.start + text.length);
      });
    }).catch(reason => { if (current()) { setError(asrErrorCode(reason)); void refresh(); } })
      .finally(() => {
        if (active.current === capture) { active.current = null; if (mounted.current) setRecognizing(false); }
        // Drop the result from the server's short-lived receipt as soon as it is consumed.
        void asrApi.cancel(capture.operation).catch(() => undefined);
      });
  }, [recording.phase, recording.audio, recorder, textareaRef, refresh]);

  const start = () => {
    if (disabled || !status?.ready) return;
    cancel(); setError(null);
    const value = latest.current;
    const area = textareaRef.current;
    active.current = { operation: createASROperation(status.runtime_id, status.config_revision), abort: new AbortController(),
      scope: scopeKey, revision: value.revision, draft: value.draft,
      start: area?.selectionStart ?? value.draft.length, end: area?.selectionEnd ?? value.draft.length, submitted: false };
    void recorder.start();
  };
  const configure = () => {
    const shell = useChatShellStore.getState();
    shell.setSettingsNavigationIntent({ section: 'asr' });
    shell.setActivePanel('settings');
  };
  const capturing = ['requesting', 'recording', 'stopping'].includes(recording.phase);
  const failure = error ?? recording.error?.code ?? (status?.enabled && !status.ready ? status.error : null);
  return <div className="flex max-w-sm flex-wrap items-center gap-1">
    <button type="button" disabled={disabled || capturing || recognizing} onClick={status?.ready ? start : configure}
      aria-label={t('asr.record')} title={t(status?.ready ? 'asr.record' : 'asr.configure')}
      className="rounded-md p-2 text-muted-foreground hover:bg-muted disabled:opacity-40"><Mic size={16} /></button>
    {recording.phase === 'recording' && <button type="button" onClick={() => { void recorder.stop(); }} aria-label={t('asr.stop')} className="rounded-md p-2 text-destructive"><Square size={16} /></button>}
    {(capturing || recognizing || preview) && <button type="button" onClick={cancel} aria-label={t('asr.cancel')} className="rounded-md p-2"><X size={16} /></button>}
    {(capturing || recognizing) && <span role="status" className="text-xs">{t(recognizing ? 'asr.recognizing' : 'asr.recording', { seconds: recording.seconds.toFixed(1) })}</span>}
    {failure && <span role="alert" className="text-xs text-destructive">{t(`asr.errors.${failure}`, { defaultValue: t('asr.errors.request_failed') })}</span>}
    {preview && <div className="basis-full space-y-1 text-xs"><p>{t('asr.draftChanged')}</p><p className="max-h-24 overflow-auto whitespace-pre-wrap">{preview}</p>
      <button type="button" disabled={disabled} className="underline" onClick={() => {
        if (composing.current) return;
        const value = latest.current.draft;
        const startAt = textareaRef.current?.selectionStart ?? value.length;
        const endAt = textareaRef.current?.selectionEnd ?? value.length;
        latest.current.onInsert(value.slice(0, startAt) + preview + value.slice(endAt)); setPreview(null);
      }}>{t('asr.insert')}</button></div>}
  </div>;
});
