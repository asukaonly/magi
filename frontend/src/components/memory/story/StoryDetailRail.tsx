import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { StoryItem } from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';

interface StoryDetailRailProps {
  story: StoryItem | null;
  onClose: () => void;
  onSaveNote: (note: string) => Promise<void> | void;
}

export const StoryDetailRail = ({ story, onClose, onSaveNote }: StoryDetailRailProps) => {
  const { t, i18n } = useTranslation('app');
  const [note, setNote] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const existing = (story?.insight_metadata?.user_note ?? '') as string;
    setNote(existing);
    setSaved(false);
  }, [story?.summary_id]);

  if (!story) return null;

  const handleSave = async () => {
    await onSaveNote(note);
    setSaved(true);
  };

  const period = story.period_end ? new Date(story.period_end * 1000).toLocaleString(i18n.language) : '';

  return (
    <aside
      data-testid="story-detail-rail"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-lg flex-col border-l border-[hsl(var(--memory-border)/0.6)] bg-[hsl(var(--memory-panel-elevated)/0.96)] shadow-2xl"
    >
      <header className="flex items-start justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.6)] px-6 py-4">
        <div>
          <div className="text-xs text-[hsl(var(--memory-muted))]">
            {t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category })}
            {period ? ` · ${period}` : ''}
          </div>
          <h2 className="mt-1 text-lg font-semibold text-[hsl(var(--memory-title))]">{story.title || story.content.slice(0, 80)}</h2>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="close">
          <X className="h-4 w-4" />
        </Button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-4 text-sm leading-6 text-[hsl(var(--memory-body))]">
        <p>{story.content}</p>

        <div>
          <div className="text-xs font-medium text-[hsl(var(--memory-muted))]">
            {t('memory.stories.detailRail.evidenceTitle')}
          </div>
          <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.stories.evidenceChip', { count: story.evidence_event_count })}
          </div>
        </div>

        <div>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t('memory.stories.detailRail.notePlaceholder')}
            className="w-full rounded-sm border border-[hsl(var(--memory-input-border)/0.7)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm"
            rows={4}
          />
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" onClick={handleSave}>{t('memory.stories.actions.addNote')}</Button>
            {saved ? (
              <span className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.stories.detailRail.savedNote')}</span>
            ) : null}
          </div>
        </div>
      </div>
    </aside>
  );
};

export default StoryDetailRail;
