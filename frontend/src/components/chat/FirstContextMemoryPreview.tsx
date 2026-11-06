import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import { memoryApi } from '@/api/modules/memory';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import { MemoryEvidenceButton } from '@/components/memory/evidence/MemoryEvidenceButton';
import { Button } from '@/components/ui/button';
import { DEFAULT_USER_ID } from '@/constants';
import { APP_EVENTS } from '@/constants/events';
import { portraitEvidenceIds } from '@/domain/memory/evidence';
import { useAppNavigate } from '@/hooks/useAppNavigate';

const itemSchema = z.object({
  id: z.string().min(1), text: z.string().trim().min(1), source: z.string(),
  assertion_id: z.string().nullable(), updated_at: z.number().nullable().optional(),
  display_status: z.enum(['complete', 'partial', 'unavailable']).optional(),
  evidence_basis: z.enum(['direct_report', 'user_confirmed', 'inferred', 'unknown']).optional(),
  basis_refs: z.array(z.string()),
});
const itemsSchema = z.object({ items: z.array(itemSchema) });
const portraitSchema = z.object({
  is_stale: z.boolean(),
  self_view: z.object({ world: z.object({ groups: z.array(itemsSchema) }), recent: itemsSchema }),
});
const sourcesSchema = z.object({ items: z.array(z.object({
  event_id: z.string().min(1), source_item_id: z.string().nullable(), source: z.string(),
  author_type: z.string().nullable(), session_id: z.string().nullable(), user_id: z.string().nullable(),
})) });
type PreviewItem = z.infer<typeof itemSchema> & { recent: boolean };
type PreviewState = { key: string; status: 'processing' | 'ready' | 'pending' | 'error'; items: PreviewItem[] };

export function FirstContextMemoryPreview({ sessionId, sourceMessageIds, onAsk }: {
  sessionId: string;
  sourceMessageIds: string[];
  onAsk: (question: string) => void;
}) {
  const { t } = useTranslation('app');
  const navigate = useAppNavigate();
  const sourceKey = JSON.stringify([...new Set(sourceMessageIds)].slice(-3));
  const key = `${sessionId}:${sourceKey}`;
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState<PreviewState>({ key, status: 'processing', items: [] });
  const view = snapshot.key === key ? snapshot : { status: 'processing', items: [] };

  useEffect(() => {
    const ids = z.array(z.string()).parse(JSON.parse(sourceKey));
    let active = true;
    let blocked = false;
    let revision = 0;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const update = (status: PreviewState['status'], items: PreviewItem[] = []) => setSnapshot({ key, status, items });
    const poll = async () => {
      if (!active || blocked || !ids.length) return;
      clearTimeout(timer);
      const owner = ++revision;
      update('processing');
      if (polls++ >= 6) { update('pending'); return; }
      try {
        const [rawPortrait, ...sources] = await Promise.all([
          memoryPortraitSelfApi.get(DEFAULT_USER_ID),
          ...ids.map((id) => memoryApi.getL1Events({ source: 'chat', source_item_id: id, session_id: sessionId, user_id: DEFAULT_USER_ID, limit: 1 })),
        ]);
        if (!active || owner !== revision) return;
        const portrait = portraitSchema.parse(rawPortrait);
        const refs = new Set(sources.flatMap((source, index) => sourcesSchema.parse(source).items
          .filter((event) => event.source === 'chat' && event.author_type === 'user' && event.user_id === DEFAULT_USER_ID
            && event.session_id === sessionId && event.source_item_id === ids[index])
          .map((event) => `event:${event.event_id}`)));
        const seen = new Set<string>();
        const items = portrait.is_stale ? [] : [
          ...portrait.self_view.world.groups.flatMap((group) => group.items.map((item) => ({ ...item, recent: false }))),
          ...portrait.self_view.recent.items.map((item) => ({ ...item, recent: true })),
        ].filter((item) => {
          if (seen.has(item.id) || item.display_status !== 'complete'
            || !['direct_report', 'user_confirmed'].includes(item.evidence_basis ?? '')
            || !item.basis_refs.some((ref) => refs.has(ref))) return false;
          seen.add(item.id);
          return true;
        }).slice(0, 2);
        update(items.length ? 'ready' : polls < 6 ? 'processing' : 'pending', items);
        if (!items.length && polls < 6) timer = setTimeout(() => { void poll(); }, 5000);
      } catch { if (active && owner === revision) update('error'); }
    };
    const invalidate = () => { blocked = true; revision += 1; clearTimeout(timer); update('pending'); };
    const maintenance = (event: Event) => {
      const detail: unknown = event instanceof CustomEvent ? event.detail : null;
      if (detail && typeof detail === 'object' && 'status' in detail && detail.status === 'idle') { blocked = false; void poll(); }
      else invalidate();
    };
    const changed = (event: Event) => {
      const detail: unknown = event instanceof CustomEvent ? event.detail : null;
      if (detail && typeof detail === 'object' && 'resource' in detail && detail.resource !== 'memory') return;
      void poll();
    };
    void poll();
    window.addEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, invalidate);
    window.addEventListener(APP_EVENTS.CENTER_MAINTENANCE, maintenance);
    window.addEventListener(APP_EVENTS.CENTER_STATE_CHANGED, changed);
    return () => {
      active = false; clearTimeout(timer);
      window.removeEventListener(APP_EVENTS.MEMORY_CLEAR_STARTED, invalidate);
      window.removeEventListener(APP_EVENTS.CENTER_MAINTENANCE, maintenance);
      window.removeEventListener(APP_EVENTS.CENTER_STATE_CHANGED, changed);
    };
  }, [key, sessionId, sourceKey, attempt]);

  if (sourceKey === '[]') return null;
  return <section className="mb-3 rounded-xl border border-border bg-muted/20 p-4" data-testid="first-context-memory-preview">
    <p role="status" className="text-sm font-medium">{t(`chat.firstContextMemory.${view.status}`)}</p>
    {view.status !== 'ready' ? <Button type="button" size="sm" variant="ghost" onClick={() => setAttempt((value) => value + 1)}>{t('chat.firstContextMemory.refresh')}</Button>
      : view.items.map((item) => <article key={item.id} className="mt-3 space-y-1">
        <p className="text-sm leading-6">{item.text}</p>
        {item.recent && <p className="text-xs text-muted-foreground">{t('chat.firstContextMemory.recent')}</p>}
        <div className="flex flex-wrap gap-1">
          <MemoryEvidenceButton target={{ title: item.text, recordRef: item.assertion_id ? { kind: 'assertion', id: item.assertion_id } : undefined,
            eventIds: portraitEvidenceIds(item.basis_refs), source: item.source, occurredAt: item.updated_at }} onChanged={() => setAttempt((value) => value + 1)} />
          <Button type="button" size="sm" variant="ghost" onClick={() => onAsk(t('chat.firstContextMemory.question', { value: item.text }))}>{t('chat.firstContextMemory.tryRecall')}</Button>
        </div>
      </article>)}
    <Button type="button" size="sm" variant="ghost" className="px-0 text-xs text-muted-foreground" onClick={() => navigate('/memory/portrait')}>{t('chat.firstContextMemory.viewAll')}</Button>
  </section>;
}
