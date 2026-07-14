import { useTranslation } from 'react-i18next';
import type { StoryItem } from '@/api/modules/memoryStories';
import { MEMORY_SECTION_SURFACE_CLASS } from '../MemoryPageFrame';
import {
  sanitizeMemoryText,
  storyDisplayTitle,
} from './overviewModel';

export function OverviewRecentStories({ stories }: { stories: StoryItem[] }) {
  const { t } = useTranslation('app');

  if (stories.length === 0) {
    return null;
  }

  return (
    <section className={MEMORY_SECTION_SURFACE_CLASS}>
      <h2 className="text-lg font-semibold tracking-[-0.015em] text-[hsl(var(--memory-title))]">
        {t('memory.overview.sections.recent')}
      </h2>
      <div className="mt-4 divide-y divide-[hsl(var(--memory-divider)/0.34)]">
        {stories.map((story) => (
          <article key={story.summary_id} className="py-4 first:pt-1 last:pb-1">
            <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
              {storyDisplayTitle(story, t)}
            </div>
            <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
              {sanitizeMemoryText(story.preview_text || story.content, t)}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}
