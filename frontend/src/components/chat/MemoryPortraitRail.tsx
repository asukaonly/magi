import { useTranslation } from 'react-i18next';
import { useMemoryPortrait } from '@/hooks/useMemoryPortrait';
import { Button } from '@/components/ui/button';
import { PortraitCard } from './portrait/PortraitCard';
import { PortraitColdStart } from './portrait/PortraitColdStart';

export interface MemoryPortraitRailProps {
  sessionId: string;
  userId: string;
  personaId: string;
}

export const MemoryPortraitRail = ({
  sessionId,
  userId,
  personaId,
}: MemoryPortraitRailProps) => {
  const { t } = useTranslation('app');
  const { payload, isLoading, error, refresh } = useMemoryPortrait({ sessionId, userId, personaId });

  if (!sessionId) {
    return null;
  }

  const hasObservations = (payload?.observations.length ?? 0) > 0;
  const computing = payload?.cold_start_reason === 'computing' || payload?.is_stale;
  const showColdStart = payload && !error && !computing && (payload.is_cold_start || !hasObservations);

  return (
    <aside
      className="flex h-full min-h-0 w-[320px] shrink-0 flex-col border-l border-border/60 bg-background/70"
      data-testid="memory-portrait-rail"
      aria-label={t('chat.portrait.title')}
    >
      <div className="flex h-11 shrink-0 items-center px-4 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {t('chat.portrait.title')}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3 pr-2 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        {isLoading || computing ? <p role="status" className="text-sm text-muted-foreground">{t('chat.portrait.processing')}</p> : null}
        {error ? <div role="alert" className="text-sm">
          <p>{t(payload ? 'chat.portrait.staleError' : 'chat.portrait.loadError')}</p>
          <Button variant="ghost" onClick={refresh}>{t('memory.portrait.loadFailed.retry')}</Button>
        </div> : null}
        {showColdStart ? (
          <PortraitColdStart line={payload?.cold_start_line ?? null} />
        ) : (
          payload?.observations.map((obs, idx) => (
            <PortraitCard key={`${obs.kind}-${idx}`} observation={obs} />
          ))
        )}
      </div>
    </aside>
  );
};
