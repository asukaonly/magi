import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowUpRight, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { TimelineClusterBlock, TimelineContextBundle } from '@/api/modules/timeline';
import { openExternalUrl } from '@/runtime/desktop';
import { SourceIcon, labelForSource } from './SourceIcon';
import { cleanText, formatClock, httpUrl, readableText, sceneBody, sceneTitle } from './scene-presentation';

interface Props {
  cluster: TimelineClusterBlock;
  context: TimelineContextBundle | null;
  loading: boolean;
  failed: boolean;
  onClose: () => void;
  onRetry: () => void;
  onOpenExperience?: (id: string) => void;
  onOrganizeExperience?: () => void;
}

interface EvidenceItem {
  id: string;
  source: string;
  title: string;
  summary: string;
  timestamp: number;
  url: string | null;
  prompts: string[];
  count: number;
  visitCount: number | null;
}

function evidenceItems(context: TimelineContextBundle | null): EvidenceItem[] {
  const records = context?.l1_events ?? [];
  const byId = new Map(records.map(item => [cleanText(item.event_id), item]));
  for (const excerpt of context?.chat_excerpts ?? []) {
    const id = cleanText(excerpt.event_id);
    byId.set(id, { ...byId.get(id), ...excerpt, event_id: id, source_type: 'chat', summary: excerpt.content });
  }
  const items: EvidenceItem[] = [];
  const pages = new Map<string, EvidenceItem>();
  for (const record of [...byId.values()].sort((left, right) =>
    (typeof left.timestamp === 'number' ? left.timestamp : 0) - (typeof right.timestamp === 'number' ? right.timestamp : 0))) {
    const source = cleanText(record.source_type) || 'memory';
    const url = httpUrl(record.url);
    const prompts = Array.isArray(record.user_prompts)
      ? record.user_prompts.filter((text): text is string => typeof text === 'string' && Boolean(text.trim())) : [];
    const item: EvidenceItem = {
      id: cleanText(record.event_id), source,
      title: readableText(record.title), summary: readableText(record.summary) || readableText(record.content),
      timestamp: typeof record.timestamp === 'number' ? record.timestamp : 0,
      url, prompts, count: 1,
      visitCount: typeof record.visit_count === 'number' && record.visit_count > 0 ? record.visit_count : null,
    };
    const key = url ? `${source}:${url}` : '';
    const existing = key ? pages.get(key) : undefined;
    if (existing) {
      existing.count += 1;
      existing.visitCount = existing.visitCount !== null && item.visitCount !== null ? existing.visitCount + item.visitCount : null;
      continue;
    }
    if (key) pages.set(key, item);
    items.push(item);
  }
  return items.sort((left, right) => left.timestamp - right.timestamp);
}

export function EvidenceReader({ cluster, context, loading, failed, onClose, onRetry, onOpenExperience, onOrganizeExperience }: Props) {
  const { t } = useTranslation('app');
  const readerRef = useRef<HTMLElement>(null);
  const [visibleCount, setVisibleCount] = useState(30);
  const items = useMemo(() => evidenceItems(context), [context]);
  const source = cluster.source_types?.[0] || 'memory';
  const title = sceneTitle(cluster, labelForSource(source, t));
  const body = sceneBody(cluster, title);
  useEffect(() => {
    const frame = requestAnimationFrame(() => readerRef.current?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, []);

  return <section ref={readerRef} tabIndex={-1} id="timeline-evidence-reader" data-testid="timeline-context-drawer"
    className="timeline-evidence outline-hidden" aria-label={t('timeline.review.details')}>
    <header className="mb-5">
      <button type="button" onClick={onClose} className="mb-5 inline-flex items-center gap-2 rounded-md px-1 py-1.5 text-[13px] text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />{t('timeline.review.back')}
      </button>
      <div className="flex items-start gap-3">
        <SourceIcon sourceType={source} className="mt-0.5 h-7 w-7 shrink-0" />
        <div className="min-w-0"><h2 className="text-[20px] font-semibold leading-7 wrap-anywhere">{title}</h2>
          <p className="mt-1 text-[12px] text-muted-foreground">{labelForSource(source, t)} · {formatClock(cluster.time_start)}
            {cluster.time_end > cluster.time_start ? `–${formatClock(cluster.time_end)}` : ''}
          </p>
        </div>
      </div>
      {body ? <p className="mt-4 text-[14px] leading-7 text-foreground/80 wrap-anywhere">{body}</p> : null}
      {cluster.experience_id ? <button type="button" onClick={() => onOpenExperience?.(cluster.experience_id!)}
        disabled={!onOpenExperience} className="mt-3 text-[12px] text-primary hover:underline disabled:text-muted-foreground">
        {cluster.experience_title || t('timeline.immersive.scene.relation.openExperience')}
        {cluster.experience_chapter_id ? ` · ${t('timeline.immersive.scene.kind.chapter')}` : ''}
      </button> : onOrganizeExperience ? <button type="button" onClick={onOrganizeExperience} className="mt-3 text-[12px] text-muted-foreground hover:text-foreground">
        {t('timeline.immersive.scene.relation.organize')}
      </button> : null}
    </header>
    {loading ? <p role="status" className="flex items-center gap-2 py-10 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t('timeline.immersive.scene.drawer.loading')}</p>
      : failed ? <div role="alert" className="py-6 text-sm text-muted-foreground"><p>{t('timeline.immersive.scene.drawer.failed')}</p><button type="button" onClick={onRetry} className="mt-3 text-primary hover:underline">{t('timeline.review.retry')}</button></div>
      : items.length === 0 ? <p className="border-t border-border/60 py-6 text-sm text-muted-foreground">{t('timeline.immersive.scene.drawer.empty')}</p>
      : <><p className="mb-2 text-[12px] text-muted-foreground">{t('timeline.review.records', { count: context?.l1_events.length || items.length })}</p>
        <div className="divide-y divide-border/55 border-t border-border/55">
          {items.slice(0, visibleCount).map(item => <EvidenceRecord key={item.id} item={item} />)}
        </div>
        {items.length > visibleCount ? <button type="button" onClick={() => setVisibleCount(count => count + 30)} className="my-4 rounded-md px-3 py-2 text-[13px] text-primary hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
          {t('timeline.review.loadMore', { count: items.length - visibleCount })}
        </button> : null}
      </>}
  </section>;
}

function EvidenceRecord({ item }: { item: EvidenceItem }) {
  const { t } = useTranslation('app');
  const [opening, setOpening] = useState(false);
  const agent = item.source.endsWith('_agent_history');
  const title = item.title || labelForSource(item.source, t);
  const summary = item.url && (item.summary === title || /^[(（](?:\d+ visits|访问 \d+ 次)[)）]$/.test(item.summary.slice(title.length).trim()) && item.summary.startsWith(title))
    ? '' : item.summary !== title ? item.summary : '';
  const open = async () => {
    if (!item.url || opening) return;
    setOpening(true);
    try { await openExternalUrl(item.url); }
    catch { toast.error(t('timeline.review.openFailed')); }
    finally { setOpening(false); }
  };
  return <article className="py-4 wrap-anywhere">
    <div className="flex items-start gap-2.5">
      <SourceIcon sourceType={item.source} className="mt-0.5 h-[18px] w-[18px] shrink-0" />
      <div className="min-w-0 flex-1">
        {item.url ? <button type="button" onClick={() => void open()} disabled={opening} className="inline-flex items-start gap-1.5 rounded-sm text-left text-[14px] font-medium leading-6 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring">
          {title}<ArrowUpRight className="mt-1 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        </button> : <h3 className="text-[14px] font-medium leading-6">{title}</h3>}
        <p className="mt-1 flex flex-wrap gap-x-2 text-[12px] text-muted-foreground">
          {item.url ? <span>{new URL(item.url).hostname}</span> : <span>{labelForSource(item.source, t)}</span>}
          {item.timestamp > 0 ? <time>{formatClock(item.timestamp)}</time> : null}
          {item.visitCount !== null && item.visitCount > 1 ? <span>{t('timeline.review.visits', { count: item.visitCount })}</span>
            : item.count > 1 ? <span>{t('timeline.review.mergedRecords', { count: item.count })}</span> : null}
        </p>
        {item.prompts.length > 0 ? <div className="mt-4 space-y-4">
          <p className="text-[12px] text-muted-foreground">{t('timeline.review.yourRequests')}</p>
          {item.prompts.map((prompt, index) => <p key={index} className="whitespace-pre-wrap text-[14px] leading-7 text-foreground/85">{prompt}</p>)}
        </div> : summary ? <p className="mt-3 whitespace-pre-wrap text-[14px] leading-7 text-foreground/85">{summary}</p>
          : agent ? <p className="mt-3 text-[13px] text-muted-foreground">{t('timeline.review.noRequests')}</p> : null}
      </div>
    </div>
  </article>;
}
