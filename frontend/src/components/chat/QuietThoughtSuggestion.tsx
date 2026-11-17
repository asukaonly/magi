import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { personaThoughtsApi, type PersonaThought } from '@/api/modules/personaThoughts';
import { Button } from '@/components/ui/button';
import { APP_EVENTS } from '@/constants/events';

export function QuietThoughtSuggestion({ busy, onDiscuss }: { busy: boolean; onDiscuss: (text: string) => void }) {
  const { t } = useTranslation('app');
  const [thought, setThought] = useState<PersonaThought | null>(null);
  const attempted = useRef(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const invalidate = (event: Event) => {
      const detail: unknown = event instanceof CustomEvent ? event.detail : null;
      if (event.type === APP_EVENTS.CENTER_STATE_CHANGED && detail && typeof detail === 'object'
        && 'resource' in detail && typeof detail.resource === 'string'
        && !['memory', 'personality', 'personas', 'config'].includes(detail.resource)) return;
      setThought(null); setRevision((value) => value + 1);
    };
    const visibilityChanged = () => setRevision((value) => value + 1);
    window.addEventListener(APP_EVENTS.CENTER_STATE_CHANGED, invalidate);
    window.addEventListener(APP_EVENTS.CENTER_MAINTENANCE, invalidate);
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => {
      window.removeEventListener(APP_EVENTS.CENTER_STATE_CHANGED, invalidate);
      window.removeEventListener(APP_EVENTS.CENTER_MAINTENANCE, invalidate);
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  }, []);
  useEffect(() => {
    if (busy || attempted.current) return;
    const controller = new AbortController();
    let pending = false;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible' || pending || attempted.current) return;
      pending = true;
      void personaThoughtsApi.share(controller.signal).then((result) => {
        if (!controller.signal.aborted && result) {
          attempted.current = true; window.clearInterval(timer); setThought(result);
        }
      }).catch(() => { /* Optional sharing must not interrupt the conversation. */ })
        .finally(() => { pending = false; });
    }, 30_000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [busy, revision]);
  if (busy || !thought) return null;
  return <aside aria-label={t('personality.thoughts.title')} className="mx-6 mb-2 rounded-xl border border-border/50 p-3">
    <p className="text-sm leading-6">{thought.content}</p>
    <div className="mt-2 flex gap-2"><Button size="sm" variant="outline" onClick={() => {
      onDiscuss(t('personality.thoughts.discussPrompt', { topic: thought.topic, content: thought.content })); setThought(null);
    }}>{t('personality.thoughts.discuss')}</Button>
      <Button size="sm" variant="ghost" onClick={() => setThought(null)}>{t('personality.thoughts.cancel')}</Button></div>
  </aside>;
}
