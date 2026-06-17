import { MapPin, Tags, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import type { L2Episode, L2EpisodeReviewDetail, L2EpisodeWithSummary } from '@/api/modules/memory';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { formatEpisodeTimeRange } from './EpisodeRow';
import EpisodeEventList from './EpisodeEventList';
import EpisodeNarrative from './EpisodeNarrative';

type EpisodeReviewLike = L2Episode | L2EpisodeWithSummary | L2EpisodeReviewDetail;

const normalizeList = (items: string[] | null | undefined): string[] => (
  Array.isArray(items) ? items.filter((item) => Boolean(item && item.trim())) : []
);

const MEMORY_INFO_PANEL_CLASS = 'rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.5)] px-4 py-3 text-sm text-[hsl(var(--memory-muted))]';

export function EpisodeDetail({
  episode,
  title,
  detailLoading,
}: {
  episode: EpisodeReviewLike;
  title: string;
  detailLoading: boolean;
}) {
  const { t, i18n } = useTranslation('app');
  const events = 'events' in episode ? episode.events : [];
  const range = formatEpisodeTimeRange(episode.time_start, episode.time_end, i18n.language);
  const typeLabel = t(`memory.episodes.filters.${episode.episode_type || 'activity'}`, {
    defaultValue: episode.episode_type || '',
  });

  return (
    <div className="min-w-0">
      <header className="border-b border-[hsl(var(--memory-divider)/0.62)] px-5 py-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {typeLabel ? (
                <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.76)] text-[hsl(var(--memory-body))]">
                  {typeLabel}
                </Badge>
              ) : null}
              {episode.user_pinned ? (
                <Badge variant="outline" className="rounded-md border-[hsl(var(--memory-accent)/0.24)] bg-[hsl(var(--memory-accent-soft)/0.62)] text-[hsl(var(--memory-title))]">
                  {t('memory.episodes.fields.pinned')}
                </Badge>
              ) : null}
            </div>
            <h2 className="mt-2 break-words text-xl font-semibold leading-7 text-[hsl(var(--memory-title))]">{title}</h2>
            {range ? <p className="mt-1 text-sm text-[hsl(var(--memory-muted))]">{range}</p> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm">{t('memory.episodes.actions.rename')}</Button>
            <Button variant="outline" size="sm">{t('memory.episodes.actions.editDescription')}</Button>
            <Button variant="outline" size="sm">{t('memory.episodes.actions.regenerateDescription')}</Button>
          </div>
        </div>
      </header>

      <div className="space-y-5 px-5 py-5">
        {detailLoading ? <div className={MEMORY_INFO_PANEL_CLASS}>{t('common.loading')}</div> : null}
        <EpisodeNarrative episode={episode} />
        <div className="grid gap-3 md:grid-cols-3">
          <TagGroup
            icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.people')}
            values={normalizeList(episode.primary_entity_ids)}
          />
          <TagGroup
            icon={<MapPin className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.places')}
            values={normalizeList(episode.primary_place_ids)}
          />
          <TagGroup
            icon={<Tags className="h-4 w-4" aria-hidden="true" />}
            title={t('memory.episodes.sections.topics')}
            values={normalizeList(episode.primary_topic_keys)}
          />
        </div>
        <EpisodeEventList events={events} />
      </div>
    </div>
  );
}

function TagGroup({ icon, title, values }: { icon: ReactNode; title: string; values: string[] }) {
  const { t } = useTranslation('app');
  return (
    <section className="min-w-0 rounded-xl border border-[hsl(var(--memory-border)/0.48)] bg-[hsl(var(--memory-panel-subtle)/0.46)] px-3 py-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <span className="text-[hsl(var(--memory-accent))]">{icon}</span>
        {title}
      </h3>
      <div className="mt-3 flex flex-wrap gap-2">
        {values.length > 0 ? values.map((value) => (
          <span key={value} className="min-w-0 rounded-md border border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
            {value}
          </span>
        )) : (
          <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.noTags')}</span>
        )}
      </div>
    </section>
  );
}

export default EpisodeDetail;
