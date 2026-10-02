import { createContext, useContext, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { Volume2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTTS } from '@/hooks/useTTS';
import { messageSource } from '@/lib/audio/tts-controller';
import type { ChatTimelineMessage } from '@/domain/chat/state';
import { useRealtime } from '@/realtime/provider';
import { parseChatMessage } from '@/api/event-contract';
import { isRecord } from '@/utils/value-guards';
import { Switch } from '@/components/ui/switch';
import { TTSPlaybackControls } from './TTSPlaybackControls';
import { subscribeRuntimeReconnect } from '@/runtime/config';

const Context = createContext<((message: ChatTimelineMessage) => void) | null>(null);
const AUTO_KEY = 'magi.tts.auto.v1';

export function TTSChatProvider({ sessionId, messages, submittedTurns, children }: PropsWithChildren<{
  sessionId: string | null; messages: ChatTimelineMessage[]; submittedTurns: Readonly<Record<string, string>>;
}>) {
  const { t } = useTranslation('app');
  const { subscribe } = useRealtime();
  const { controller, state } = useTTS(`chat:${sessionId ?? ''}`);
  const [automatic, setAutomatic] = useState(() => localStorage.getItem(AUTO_KEY) === 'true');
  const source = useRef<{ id: string; text: string } | null>(null);
  const autoCycle = useRef({ since: Date.now(), seen: new Set<string>(), turns: new Set<string>() });
  const activePending = sessionId ? submittedTurns[sessionId] : undefined;
  useEffect(() => {
    autoCycle.current = { since: Date.now(), seen: new Set(), turns: new Set() };
    return subscribeRuntimeReconnect(() => {
      autoCycle.current = { since: Date.now(), seen: new Set(), turns: new Set() };
    });
  }, [sessionId, automatic]);
  useEffect(() => {
    if (automatic && activePending) autoCycle.current.turns.add(activePending);
  }, [automatic, activePending]);
  useEffect(() => {
    const current = source.current;
    if (current && !messages.some((message) => message.messageId === current.id && message.content === current.text)) {
      source.current = null; controller.stop();
    }
  }, [messages, controller]);
  useEffect(() => subscribe((event) => {
    if (['resync_required', 'connection_interrupted'].includes(event.event ?? event.type ?? '')) {
      autoCycle.current = { since: Date.now(), seen: new Set(), turns: new Set() };
      source.current = null; controller.stop(); return;
    }
    if ((event.event ?? event.type) === 'chat_message_hidden' && isRecord(event.data)
      && event.data.session_id === sessionId && event.data.message_id === source.current?.id) {
      source.current = null; controller.stop(); return;
    }
    if ((event.event ?? event.type) !== 'chat_message_upserted' || !isRecord(event.data) || event.data.session_id !== sessionId) return;
    let message;
    try { message = parseChatMessage(event.data.message); } catch { return; }
    if (source.current && source.current.id === message.message_id && source.current.text !== message.content) { controller.stop(); return; }
    if (!automatic || !sessionId || message.role !== 'assistant' || message.kind !== 'assistant' || !message.message_id
      || !['assistant_final', 'assistant_rhythm_segment'].includes(message.message_kind ?? '')
      || !message.turn_id || !autoCycle.current.turns.has(message.turn_id) || message.timestamp < autoCycle.current.since) return;
    const key = message.message_id;
    if (autoCycle.current.seen.has(key)) return;
    autoCycle.current.seen.add(key);
    if (!controller.canAutoplay()) return;
    source.current = { id: message.message_id, text: message.content };
    void controller.speak(messageSource(sessionId, message.message_id, message.content), message.message_id, 'auto');
  }), [automatic, controller, sessionId, subscribe]);
  const speak = useMemo(() => (message: ChatTimelineMessage) => {
    if (!sessionId || !message.messageId || message.streaming) return;
    source.current = { id: message.messageId, text: message.content };
    void controller.speak(messageSource(sessionId, message.messageId, message.content), message.messageId);
  }, [controller, sessionId]);
  return <Context.Provider value={speak}><div className="flex h-full min-h-0 flex-col">
    <div className="flex flex-wrap items-center justify-between gap-2 px-2">
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <Switch aria-label={t('tts.automatic')} checked={automatic} onCheckedChange={(enabled) => {
          localStorage.setItem(AUTO_KEY, String(enabled)); setAutomatic(enabled); controller.stop();
        }} />{t('tts.automatic')}
      </label>
      <TTSPlaybackControls controller={controller} state={state} />
    </div>
    {children}
  </div></Context.Provider>;
}

export function ReadMessageButton({ message }: { message: ChatTimelineMessage }) {
  const speak = useContext(Context);
  const { t } = useTranslation('app');
  if (!speak || message.role !== 'assistant' || message.kind !== 'assistant' || !message.messageId || message.streaming
    || !['assistant_final', 'assistant_rhythm_segment'].includes(message.messageKind ?? '')) return null;
  return <button type="button" aria-label={t('tts.read')} title={t('tts.read')}
    className="rounded p-1 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    onClick={() => speak(message)}><Volume2 className="h-4 w-4" /></button>;
}
