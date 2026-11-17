import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { personaThoughtsApi, type PersonaThoughtDetail } from '@/api/modules/personaThoughts';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { InlineLoadError } from '@/components/ui/inline-load-error';
import { useAppNavigate } from '@/hooks/useAppNavigate';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';
import { asEventHandler } from '@/utils/as-event-handler';

export function PersonaThoughts({ personaId, canDiscuss }: { personaId: string; canDiscuss: boolean }) {
  const { t } = useTranslation('app');
  const navigate = useAppNavigate();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const thoughts = useQuery({ queryKey: ['persona-thoughts', personaId], queryFn: ({ signal }) => personaThoughtsApi.list(personaId, signal) });
  const detail = useQuery({ queryKey: ['persona-thought', personaId, selected], enabled: selected !== null,
    queryFn: ({ signal }) => personaThoughtsApi.get(personaId, selected ?? '', signal) });
  useEffect(() => { setSelected(null); }, [personaId]);
  useCenterRefresh(async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['persona-thoughts', personaId] }),
      client.invalidateQueries({ queryKey: ['persona-thought', personaId] }),
    ]);
  }, ['personality', 'personas', 'memory', 'config']);

  const dismiss = async (id: string) => {
    setPending(id);
    try {
      await personaThoughtsApi.dismiss(personaId, id);
      await client.invalidateQueries({ queryKey: ['persona-thoughts', personaId] });
      setSelected(null);
    } catch { toast.error(t('personality.thoughts.actionFailed')); }
    finally { setPending(null); }
  };

  return <section className="space-y-3 rounded-xl border border-border/50 p-4">
    <h2 className="text-base font-semibold">{t('personality.thoughts.title')}</h2>
    {thoughts.isError ? <InlineLoadError message={t('personality.thoughts.loadFailed')} onRetry={asEventHandler(async () => { await thoughts.refetch(); })} /> : null}
    {thoughts.isPending ? <p role="status" className="text-sm text-muted-foreground">{t('personality.thoughts.loading')}</p> : null}
    {thoughts.data?.last_status === 'failed' ? <p role="status" className="text-sm text-muted-foreground">{t('personality.thoughts.runFailed')}</p> : null}
    {thoughts.data && thoughts.data.items.length === 0 ? <p className="text-sm text-muted-foreground">
      {t(thoughts.data.enabled ? 'personality.thoughts.empty' : 'personality.thoughts.disabled')}
    </p> : null}
    {!thoughts.data?.enabled ? <Button variant="ghost" onClick={() => navigate('/settings?section=personalitySettings')}>{t('personality.thoughts.settings')}</Button> : null}
    {!thoughts.isError && thoughts.data?.items.slice(0, 12).map((thought) => <article key={thought.id} className="space-y-2 border-t border-border/40 pt-3">
      <div className="flex items-center justify-between gap-3"><h3 className="font-medium">{thought.topic}</h3><span className="text-xs text-muted-foreground">{t(`personality.thoughts.kinds.${thought.kind}`)}</span></div>
      <p className="whitespace-pre-wrap text-sm leading-6">{thought.content}</p>
      <p className="text-xs text-muted-foreground">{thought.applicability}</p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={!canDiscuss} title={!canDiscuss ? t('personality.thoughts.switchFirst') : undefined}
          onClick={() => navigate('/chat', { state: { suggestedDraft: t('personality.thoughts.discussPrompt', { topic: thought.topic, content: thought.content }) } })}>{t('personality.thoughts.discuss')}</Button>
        <Button size="sm" variant="ghost" onClick={() => setSelected(thought.id)}>{t('personality.thoughts.evidence')}</Button>
        <Button size="sm" variant="ghost" disabled={pending !== null} onClick={asEventHandler(() => dismiss(thought.id))}>{t('personality.thoughts.dismiss')}</Button>
      </div>
    </article>)}
    <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null); }}>
      <DialogContent aria-describedby={undefined} className="max-h-[80vh] overflow-y-auto"><DialogHeader><DialogTitle>{t('personality.thoughts.evidence')}</DialogTitle></DialogHeader>
        {detail.isError ? <InlineLoadError message={t('personality.thoughts.loadFailed')} onRetry={asEventHandler(async () => { await detail.refetch(); })} /> : null}
        {detail.isPending ? <p role="status">{t('personality.thoughts.loading')}</p> : null}
        {detail.data && !detail.isError ? <ThoughtEvidence detail={detail.data} /> : null}
      </DialogContent>
    </Dialog>
  </section>;
}

function ThoughtEvidence({ detail }: { detail: PersonaThoughtDetail }) {
  return <div className="space-y-4">{detail.evidence.map((item) => <article key={item.event_id} className="space-y-2">
    <p className="text-xs text-muted-foreground">{item.source} · {new Date(item.occurred_at * 1000).toLocaleString()}</p>
    <p className="whitespace-pre-wrap text-sm leading-6">{item.content}</p>
  </article>)}</div>;
}
