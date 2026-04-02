import React from 'react';
import { Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { TimelineClusterBlock } from '@/api/modules/timeline';

interface HighlightCardsProps {
  highlights: TimelineClusterBlock[];
  onOpenContext: (anchorId: string) => void;
}

const formatDuration = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

export const HighlightCards: React.FC<HighlightCardsProps> = ({ highlights, onOpenContext }) => {
  const { t } = useTranslation('app');

  if (highlights.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Zap className="h-3 w-3" />
        {t('timeline.highlights.title')}
      </h3>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {highlights.map((h) => (
          <button
            key={h.block_id}
            className="rounded-lg border border-border/40 bg-card px-3.5 py-3 text-left transition-colors hover:border-border hover:bg-muted/30"
            onClick={() => onOpenContext(h.block_id)}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-sm font-medium text-foreground">{h.label}</span>
              <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/60">
                {h.event_count}
              </span>
            </div>
            {h.summary && (
              <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {h.summary}
              </p>
            )}
            <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground/50">
              <span>{formatDuration(h.duration_seconds)}</span>
              {h.keywords.length > 0 && (
                <>
                  <span>·</span>
                  <span className="truncate">{h.keywords.slice(0, 3).join(', ')}</span>
                </>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};

export default HighlightCards;
