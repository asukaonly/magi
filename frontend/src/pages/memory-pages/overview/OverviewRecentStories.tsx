import { useTranslation } from 'react-i18next';
import type { StoryItem } from '@/api/modules/memoryStories';
import {
  MEMORY_EMPTY_PANEL_CLASS,
  MEMORY_SECTION_CARD_CLASS,
} from '../MemoryPageFrame';
import {
  sanitizeMemoryText,
  storyDisplayTitle,
} from './overviewModel';

export function OverviewRecentStories({ stories }: { stories: StoryItem[] }) {
  const { t } = useTranslation('app');

  return (
    <section className={MEMORY_SECTION_CARD_CLASS}>
      <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
        {t('memory.overview.sections.recent')}
      </h2>
      <div className="mt-3 divide-y divide-[hsl(var(--memory-divider)/0.6)]">
        {stories.length > 0 ? stories.map((story) => (
          <article key={story.summary_id} className="py-3">
            <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">
              {storyDisplayTitle(story, t)}
            </div>
            <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
              {sanitizeMemoryText(story.preview_text || story.content, t)}
            </p>
          </article>
        )) : (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.overview.empty.recent')}</div>
        )}
      </div>
    </section>
  );
}
