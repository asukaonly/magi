import { Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { L2Episode, L2EpisodeReviewDetail, L2EpisodeWithSummary } from '@/api/modules/memory';

type EpisodeReviewLike = L2Episode | L2EpisodeWithSummary | L2EpisodeReviewDetail;

export const getEpisodeReviewDescription = (episode: EpisodeReviewLike): string => (
  String(
    episode.user_note ||
    (episode as L2EpisodeWithSummary).display_description ||
    (episode as L2EpisodeWithSummary).episode_summary?.content ||
    episode.summary ||
    episode.slice_narrative ||
    ''
  ).trim()
);

export function EpisodeNarrative({ episode }: { episode: EpisodeReviewLike }) {
  const { t } = useTranslation('app');
  const description = getEpisodeReviewDescription(episode);

  return (
    <section>
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <Sparkles className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
        {t('memory.episodes.sections.recap')}
      </h3>
      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-[hsl(var(--memory-body))]">
        {description || t('memory.episodes.noRecap')}
      </p>
    </section>
  );
}

export default EpisodeNarrative;
