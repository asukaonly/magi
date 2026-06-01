import { useTranslation } from 'react-i18next';
import { useMemoryPortrait } from '@/hooks/useMemoryPortrait';
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
  const { payload } = useMemoryPortrait({ sessionId, userId, personaId });

  if (!sessionId) {
    return null;
  }

  const hasObservations = (payload?.observations.length ?? 0) > 0;
  const showColdStart = !payload || payload.is_cold_start || !hasObservations;

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
