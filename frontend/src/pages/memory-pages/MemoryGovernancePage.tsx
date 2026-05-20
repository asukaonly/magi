import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import { memoryApi } from '@/api/modules/memory';
import StoryCard from '@/components/memory/story/StoryCard';
import MemoryPageFrame, { MEMORY_SECTION_CARD_CLASS } from './MemoryPageFrame';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const ForgetCenter = () => {
  const { t } = useTranslation('app');
  const [episodeId, setEpisodeId] = useState('');
  const [status, setStatus] = useState<'ok' | 'error' | null>(null);

  const handleForget = async () => {
    const id = episodeId.trim();
    if (!id) return;
    try {
      await memoryApi.forgetEpisode(id, false);
      setStatus('ok');
      setEpisodeId('');
    } catch {
      setStatus('error');
    }
  };

  return (
    <div className="mt-3 flex flex-col gap-2 md:flex-row md:items-center">
      <Input
        value={episodeId}
        onChange={(event) => setEpisodeId(event.target.value)}
        placeholder="episode_id"
        className="md:max-w-sm"
      />
      <Button onClick={() => void handleForget()} disabled={!episodeId.trim()}>
        {t('memory.episodes.actions.forget')}
      </Button>
      {status === 'ok' ? <span className="text-xs text-emerald-600">{t('memory.episodes.actions.forget')}</span> : null}
      {status === 'error' ? <span className="text-xs text-red-500">error</span> : null}
    </div>
  );
};

export const MemoryGovernancePage = () => {
  const { t } = useTranslation('app');
  const [pending, setPending] = useState<StoryItem[]>([]);

  useEffect(() => {
    void memoryStoriesApi.list({ limit: 30, offset: 0 }).then((payload) => {
      setPending(payload.items.filter((item) => item.review_state === 'pending_confirmation'));
    }).catch(() => setPending([]));
  }, []);

  const handleReview = async (story: StoryItem, state: 'confirmed' | 'rejected' | 'archived') => {
    await memoryStoriesApi.review(story.summary_id, { review_state: state });
    setPending((prev) => prev.filter((it) => it.summary_id !== story.summary_id));
  };

  return (
    <MemoryPageFrame title={t('memory.governance.title')} description={t('memory.governance.subtitle')}>
      <section className={MEMORY_SECTION_CARD_CLASS}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.governance.sections.pendingReview')}
          </h2>
          <span data-testid="governance-pending-count" className="text-sm text-[hsl(var(--memory-muted))]">
            {pending.length}
          </span>
        </div>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{t('memory.governance.pendingReviewBody')}</p>
        <div className="mt-3 space-y-2">
          {pending.map((story) => (
            <StoryCard
              key={story.summary_id}
              story={story}
              onConfirm={() => void handleReview(story, 'confirmed')}
              onReject={() => void handleReview(story, 'rejected')}
              onArchive={() => void handleReview(story, 'archived')}
              onOpenDetail={() => {}}
            />
          ))}
        </div>
      </section>

      <section className={`${MEMORY_SECTION_CARD_CLASS} mt-4`}>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.governance.sections.forget')}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
          {t('memory.governance.forgetBody', { defaultValue: '从这里删除某个实体、某段时间或某个章节的记忆。' })}
        </p>
        <ForgetCenter />
      </section>

      <section className={`${MEMORY_SECTION_CARD_CLASS} mt-4`}>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.governance.sections.privacy')}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
          {t('memory.governance.privacyBody', { defaultValue: '查看每个来源当前的隐私范围。修改在「设置」里完成。' })}
        </p>
      </section>

      <section className={`${MEMORY_SECTION_CARD_CLASS} mt-4`}>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.governance.sections.developer')}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{t('memory.governance.developerBody')}</p>
        <ul className="mt-3 grid gap-2 md:grid-cols-2">
          <li>
            <Link to="/memory/events" className="block rounded-xl border border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-4 py-3 text-sm">
              {t('memory.nav.dev.events')}
            </Link>
          </li>
          <li>
            <Link to="/memory/knowledge" className="block rounded-xl border border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-4 py-3 text-sm">
              {t('memory.nav.dev.knowledge')}
            </Link>
          </li>
          <li>
            <Link to="/memory/skills" className="block rounded-xl border border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-4 py-3 text-sm">
              {t('memory.nav.dev.skills')}
            </Link>
          </li>
        </ul>
      </section>
    </MemoryPageFrame>
  );
};

export default MemoryGovernancePage;
