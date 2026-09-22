import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CloudOff, RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { CHAT_SESSION_KEY, DEFAULT_USER_ID } from '@/constants';
import { useChatTextDraft } from '@/hooks/useChatTextDraft';
import { savedOfflineChats } from '@/runtime/chat-read-cache';
import type { OfflineConnection } from '@/runtime/offline-connection';

interface Props {
  descriptor: OfflineConnection;
  name: string;
  address: string;
  reconnecting: boolean;
  onReconnect: () => void;
  onChangeConnection: () => void;
}

/** This pre-app view intentionally owns no requests, event subscriptions, or live actions. */
export function OfflineChatView({ descriptor, name, address, reconnecting, onReconnect, onChangeConnection }: Props) {
  const { t, i18n } = useTranslation('app');
  const [chats] = useState(savedOfflineChats);
  const [sessionId, setSessionId] = useState(() => {
    let selected: string | null = null;
    try { selected = window.localStorage.getItem(CHAT_SESSION_KEY(DEFAULT_USER_ID)); }
    catch { /* Saved histories remain readable if the selection cannot be restored. */ }
    return chats.find((chat) => chat.sessionId === selected)?.sessionId ?? chats[0]?.sessionId ?? null;
  });
  const draft = useChatTextDraft(sessionId);
  const draftStatusKey = draft.saveState === 'saved' ? 'offline.draftSaved'
    : draft.clearFailed ? 'offline.draftClearUnsaved'
      : draft.text ? 'offline.draftUnsaved' : 'offline.draftUnavailable';
  const chat = chats.find((item) => item.sessionId === sessionId);
  const formatTime = (time: number) => new Date(time).toLocaleString(i18n.language);
  const select = (id: string) => {
    setSessionId(id);
    try { window.localStorage.setItem(CHAT_SESSION_KEY(DEFAULT_USER_ID), id); }
    catch { /* The selection remains usable when device storage is full. */ }
  };

  return (
    <div className="flex h-full min-h-0 flex-col text-foreground" data-testid="offline-chat-view">
      <header className="shrink-0 border-b border-border bg-muted/40 px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <h1 className="flex items-center gap-2 text-lg font-semibold"><CloudOff className="h-5 w-5" />{t('offline.title')}</h1>
            <p className="break-words text-sm">{name}</p>
            <p className="break-all text-xs text-muted-foreground">{address} · {t('offline.verifiedAt', { time: formatTime(descriptor.verifiedAtMs) })}</p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button variant="outline" onClick={onChangeConnection}>{t('connections.change')}</Button>
            <Button onClick={onReconnect} disabled={reconnecting}><RotateCw className={`h-4 w-4 ${reconnecting ? 'animate-spin' : ''}`} />{t(reconnecting ? 'offline.reconnecting' : 'offline.reconnect')}</Button>
          </div>
        </div>
        <p role="status" className="mt-3 text-sm text-muted-foreground">{t('offline.notice')}</p>
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label={t('offline.savedChats')} className="max-h-48 shrink-0 overflow-y-auto border-b border-border p-3 md:max-h-none md:w-64 md:border-b-0 md:border-r">
          <h2 className="px-3 py-2 text-xs font-medium text-muted-foreground">{t('offline.savedChats')}</h2>
          {chats.map((item) => (
            <button key={item.sessionId} type="button" onClick={() => select(item.sessionId)} aria-current={item.sessionId === sessionId ? 'page' : undefined}
              className={`mb-1 block w-full rounded-md px-3 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${item.sessionId === sessionId ? 'bg-accent text-accent-foreground' : 'hover:bg-muted'}`}>
              <span className="line-clamp-2 break-words">{item.title || t('offline.untitledChat')}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{formatTime(item.checkedAt)}</span>
            </button>
          ))}
          {chats.length === 0 && <p className="px-3 text-sm text-muted-foreground">{t('offline.noChats')}</p>}
        </nav>
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
            {chat ? (
              <div className="mx-auto max-w-3xl space-y-5">
                <h2 className="text-lg font-medium">{chat.title || t('offline.untitledChat')}</h2>
                <p className="text-xs text-muted-foreground">{t('offline.snapshotAt', { time: formatTime(chat.checkedAt) })}</p>
                {chat.history?.data.has_more && <p className="text-sm text-muted-foreground">{t('offline.recentOnly')}</p>}
                {chat.history?.data.messages.map((message, index) => (
                  <article key={message.message_id ?? `${message.timestamp}:${index}`} className="rounded-lg border border-border bg-card p-4">
                    <p className="mb-2 text-xs font-medium text-muted-foreground">{t(message.role === 'user' ? 'offline.user' : 'offline.assistant')}</p>
                    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{message.content}</p>
                    {(message.attachments?.length ?? 0) > 0 && <p className="mt-3 break-words text-xs text-muted-foreground">{t('offline.attachments', { names: message.attachments?.map((item) => item.original_name).join(', ') })}</p>}
                  </article>
                ))}
                {!chat.history && <p className="text-sm text-muted-foreground">{t('offline.noHistory')}</p>}
              </div>
            ) : <p className="text-sm text-muted-foreground">{t('offline.noHistory')}</p>}
          </div>
          {sessionId && <div className="shrink-0 border-t border-border p-4 sm:px-6">
            <div className="mx-auto max-w-3xl space-y-2">
              <label htmlFor="offline-draft" className="block text-sm font-medium">{t('offline.draft')}</label>
              <Textarea id="offline-draft" value={draft.text} onChange={(event) => draft.setText(event.target.value)} maxLength={20_000} rows={3} placeholder={t('offline.draftPlaceholder')} />
              <p role="status" className={`text-xs ${draft.saveState === 'saved' ? 'text-muted-foreground' : 'text-destructive'}`}>{t(draftStatusKey)}</p>
            </div>
          </div>}
        </main>
      </div>
    </div>
  );
}
