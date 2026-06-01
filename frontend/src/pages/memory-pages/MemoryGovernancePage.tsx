import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { memoryApi, type EpisodeReconsolidateResult } from '@/api/modules/memory';
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
      {status === 'ok' ? <span className="text-xs text-emerald-600">{t('memory.governance.forgetSuccess')}</span> : null}
      {status === 'error' ? <span className="text-xs text-red-500">{t('memory.governance.forgetError')}</span> : null}
    </div>
  );
};

const ReconsolidateEpisodes = () => {
  const { t } = useTranslation('app');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EpisodeReconsolidateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await memoryApi.reconsolidateEpisodes();
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <Button onClick={() => void handleClick()} disabled={busy}>
          {busy
            ? t('memory.governance.reconsolidateBusy', { defaultValue: '整理中...' })
            : t('memory.governance.reconsolidateRun', { defaultValue: '立即整理' })}
        </Button>
        {result ? (
          <span className="text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.governance.reconsolidateResult', {
              promoted: result.promoted,
              standouts: result.standouts,
              summaries: result.summaries_generated,
              defaultValue: '升级 {{promoted}} · 标志 {{standouts}} · 新章节 {{summaries}}',
            })}
          </span>
        ) : null}
        {error ? <span className="text-xs text-red-500">{error}</span> : null}
      </div>
    </div>
  );
};

export const MemoryGovernancePage = () => {
  const { t } = useTranslation('app');

  return (
    <MemoryPageFrame title={t('memory.governance.title')} description={t('memory.governance.subtitle')}>
      <section className={MEMORY_SECTION_CARD_CLASS}>
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
          {t('memory.governance.reconsolidateTitle', { defaultValue: '整理章节' })}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
          {t('memory.governance.reconsolidateBody', {
            defaultValue: '让 Magi 把最近形成的活动片段升级成章节，并给它们起标题。',
          })}
        </p>
        <ReconsolidateEpisodes />
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
