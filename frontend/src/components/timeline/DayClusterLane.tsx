import React from 'react';
import { Pencil, Pin } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { TimelineClusterBlock } from '@/api/modules/timeline';
import type { EpisodeAnnotationPayload } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { Textarea } from '@/components/ui/textarea';

interface DayClusterLaneProps {
  scale: 'week' | 'day';
  clusters: TimelineClusterBlock[];
  episodeAnnotationPendingId?: string | null;
  onOpenContext: (anchorId: string) => void;
  onAnnotateEpisode?: (episodeId: string, payload: EpisodeAnnotationPayload) => Promise<void> | void;
}

type SegmentKey = 'night' | 'morning' | 'afternoon' | 'evening';

interface ClusterGroup {
  key: string;
  label: string;
  clusters: TimelineClusterBlock[];
}

const formatDuration = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

const formatTimeRange = (start: number, end: number): string => {
  const fmt = (ts: number) =>
    new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }).format(
      new Date(ts * 1000),
    );
  return `${fmt(start)}–${fmt(end)}`;
};

const MODE_COLORS: Record<string, string> = {
  chrome_history: 'hsl(210 55% 58%)',
  chat: 'hsl(280 45% 58%)',
  git_activity: 'hsl(150 45% 45%)',
  terminal_history: 'hsl(35 60% 50%)',
  screen_time: 'hsl(340 50% 55%)',
  calendar: 'hsl(190 50% 48%)',
  photo_library: 'hsl(25 65% 55%)',
  netease_music: 'hsl(0 60% 58%)',
  manual_journal: 'hsl(45 55% 50%)',
};

const modeColor = (mode: string): string =>
  MODE_COLORS[mode] || `hsl(${(mode.charCodeAt(0) * 37) % 360} 35% 55%)`;

const resolveClusterAnchorId = (cluster: TimelineClusterBlock): string => {
  if (cluster.episode_id) return `episode:${cluster.episode_id}`;
  if (cluster.block_id.startsWith('episode:')) return cluster.block_id;
  return cluster.representative_event_ids[0] || cluster.block_id;
};

const formatDayLabel = (timestamp: number): string =>
  new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  }).format(new Date(timestamp * 1000));

const segmentForCluster = (cluster: TimelineClusterBlock): SegmentKey => {
  const midpoint = cluster.time_start + Math.max(0, cluster.duration_seconds) / 2;
  const hour = new Date(midpoint * 1000).getHours();
  if (hour < 6) return 'night';
  if (hour < 12) return 'morning';
  if (hour < 18) return 'afternoon';
  return 'evening';
};

const groupWeekClusters = (clusters: TimelineClusterBlock[]): ClusterGroup[] => {
  const groups = new Map<string, ClusterGroup>();
  for (const cluster of clusters) {
    const day = new Date(cluster.time_start * 1000);
    const key = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`;
    const current = groups.get(key) || {
      key,
      label: formatDayLabel(cluster.time_start),
      clusters: [],
    };
    current.clusters.push(cluster);
    groups.set(key, current);
  }
  return [...groups.values()];
};

const groupDayClusters = (
  clusters: TimelineClusterBlock[],
  t: (key: string) => string,
): ClusterGroup[] => {
  const groups = new Map<SegmentKey, ClusterGroup>();
  for (const cluster of clusters) {
    const key = segmentForCluster(cluster);
    const current = groups.get(key) || {
      key,
      label: t(`timeline.day.segments.${key}`),
      clusters: [],
    };
    current.clusters.push(cluster);
    groups.set(key, current);
  }
  const order: SegmentKey[] = ['night', 'morning', 'afternoon', 'evening'];
  return order.map((key) => groups.get(key)).filter(Boolean) as ClusterGroup[];
};

const ClusterRow: React.FC<{
  cluster: TimelineClusterBlock;
  episodeAnnotationPendingId?: string | null;
  onOpenContext: (anchorId: string) => void;
  onAnnotateEpisode?: (episodeId: string, payload: EpisodeAnnotationPayload) => Promise<void> | void;
}> = ({ cluster, episodeAnnotationPendingId, onOpenContext, onAnnotateEpisode }) => {
  const { t } = useTranslation('app');
  const [editing, setEditing] = React.useState(false);
  const [labelDraft, setLabelDraft] = React.useState('');
  const [noteDraft, setNoteDraft] = React.useState('');
  const anchorId = resolveClusterAnchorId(cluster);
  const pending = cluster.episode_id ? episodeAnnotationPendingId === cluster.episode_id : false;
  const canAnnotate = Boolean(cluster.episode_id && onAnnotateEpisode);

  const openEditor = (event: React.MouseEvent) => {
    event.stopPropagation();
    setLabelDraft(cluster.user_label || cluster.label || '');
    setNoteDraft(cluster.user_note || '');
    setEditing(true);
  };

  const handlePin = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!cluster.episode_id || !onAnnotateEpisode) return;
    await onAnnotateEpisode(cluster.episode_id, { user_pinned: !cluster.user_pinned });
  };

  const handleSaveAnnotation = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!cluster.episode_id || !onAnnotateEpisode) return;
    await onAnnotateEpisode(cluster.episode_id, {
      user_label: labelDraft.trim(),
      user_note: noteDraft.trim(),
    });
    setEditing(false);
  };

  return (
    <article
      role="button"
      tabIndex={0}
      className="group flex cursor-pointer gap-4 rounded-lg px-3 py-3 transition-colors hover:bg-muted/40 focus:outline-none focus:ring-1 focus:ring-ring/30"
      onClick={() => onOpenContext(anchorId)}
      onKeyDown={(event) => { if (event.key === 'Enter') onOpenContext(anchorId); }}
    >
      <div className="flex w-20 shrink-0 flex-col items-end pt-0.5">
        <span className="text-xs tabular-nums text-muted-foreground">
          {formatTimeRange(cluster.time_start, cluster.time_end)}
        </span>
        <span className="mt-1 text-[11px] tabular-nums text-muted-foreground/60">
          {formatDuration(cluster.duration_seconds)}
        </span>
      </div>

      <div className="flex w-1 shrink-0 flex-col items-center pt-1">
        <div
          className="h-full w-1 rounded-full"
          style={{ backgroundColor: modeColor(cluster.dominant_mode), opacity: 0.6 }}
        />
      </div>

      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-baseline gap-2">
          <h3 className="truncate text-sm font-medium text-foreground">{cluster.label}</h3>
          <span className="shrink-0 text-xs text-muted-foreground/60">
            {cluster.event_count} {t('timeline.cluster.events')}
          </span>
          {cluster.user_pinned ? (
            <span className="shrink-0 rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">
              {t('timeline.episode.pinned')}
            </span>
          ) : null}
          {canAnnotate ? (
            <div className="ml-auto flex shrink-0 items-center gap-1 opacity-80 transition-opacity group-hover:opacity-100">
              <button
                type="button"
                aria-label={t(cluster.user_pinned ? 'timeline.episode.unpin' : 'timeline.episode.pin')}
                title={t(cluster.user_pinned ? 'timeline.episode.unpin' : 'timeline.episode.pin')}
                disabled={pending}
                onClick={handlePin}
                className={`inline-flex h-7 w-7 items-center justify-center rounded-md border transition-colors disabled:opacity-50 ${
                  cluster.user_pinned
                    ? 'border-primary/35 bg-primary/10 text-primary'
                    : 'border-border/50 text-muted-foreground hover:text-foreground'
                }`}
              >
                {pending ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
              </button>
              <button
                type="button"
                aria-label={t('timeline.episode.edit')}
                title={t('timeline.episode.edit')}
                disabled={pending}
                onClick={openEditor}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border/50 text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null}
        </div>

        {cluster.summary && (
          <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
            {cluster.summary}
          </p>
        )}

        <div className="flex flex-wrap gap-1.5">
          {cluster.source_types.map((src) => (
            <span
              key={src}
              className="rounded-md bg-secondary/60 px-1.5 py-0.5 text-[11px] text-secondary-foreground"
            >
              {t(`timeline.sources.${src}`, src)}
            </span>
          ))}
          {cluster.keywords.slice(0, 4).map((kw) => (
            <span key={kw} className="text-[11px] text-muted-foreground/70">
              #{kw}
            </span>
          ))}
        </div>
        {cluster.user_note ? (
          <p className="rounded-md bg-muted/35 px-2 py-1.5 text-xs leading-relaxed text-muted-foreground">
            {cluster.user_note}
          </p>
        ) : null}
        {editing ? (
          <div className="space-y-2 rounded-md border border-border/40 bg-background/70 p-3" onClick={(event) => event.stopPropagation()}>
            <Input
              aria-label={t('timeline.episode.label')}
              value={labelDraft}
              onChange={(event) => setLabelDraft(event.target.value)}
            />
            <Textarea
              aria-label={t('timeline.episode.note')}
              value={noteDraft}
              onChange={(event) => setNoteDraft(event.target.value)}
              className="min-h-[72px] resize-none"
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={(event) => {
                  event.stopPropagation();
                  setEditing(false);
                }}
              >
                {t('timeline.episode.cancel')}
              </Button>
              <Button type="button" size="sm" disabled={pending} onClick={(event) => void handleSaveAnnotation(event)}>
                {pending ? <LoadingSpinner className="h-3.5 w-3.5" /> : null}
                {t('timeline.episode.save')}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
};

export const DayClusterLane: React.FC<DayClusterLaneProps> = ({
  scale,
  clusters,
  episodeAnnotationPendingId,
  onOpenContext,
  onAnnotateEpisode,
}) => {
  const { t } = useTranslation('app');
  const sortedClusters = [...clusters].sort((a, b) => a.time_start - b.time_start);
  const groups = scale === 'week'
    ? groupWeekClusters(sortedClusters)
    : groupDayClusters(sortedClusters, t);

  return (
    <div className="space-y-4">
      {groups.map((group) => {
        const eventCount = group.clusters.reduce((sum, cluster) => sum + cluster.event_count, 0);
        return (
          <section key={group.key} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-3 border-b border-border/30 pb-1">
              <h4 className="text-xs font-medium text-foreground">{group.label}</h4>
              <span className="shrink-0 text-[11px] text-muted-foreground/60">
                {t('timeline.cluster.groupSummary', { count: eventCount })}
              </span>
            </div>
            <div className="space-y-1">
              {group.clusters.map((cluster) => (
                <ClusterRow
                  key={cluster.block_id}
                  cluster={cluster}
                  episodeAnnotationPendingId={episodeAnnotationPendingId}
                  onOpenContext={onOpenContext}
                  onAnnotateEpisode={onAnnotateEpisode}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
};

export default DayClusterLane;
