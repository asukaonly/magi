import type { ReactNode } from 'react';
import type { SelfPortraitObservation } from '@/api/modules/memoryPortraitSelf';

interface PortraitSegmentProps {
  title: string;
  observations: SelfPortraitObservation[];
  emptyText?: string;
  renderItem?: (obs: SelfPortraitObservation) => ReactNode;
}

export const PortraitSegment = ({ title, observations, emptyText, renderItem }: PortraitSegmentProps) => (
  <section className="rounded-2xl border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-5 py-4">
    <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
    <div className="mt-2 space-y-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
      {observations.length === 0 ? (
        <p className="text-xs text-[hsl(var(--memory-muted))]">{emptyText ?? '—'}</p>
      ) : (
        observations.map((obs, index) => (
          <div key={`${obs.kind}-${index}`}>
            {renderItem ? renderItem(obs) : (
              <p>{obs.text}</p>
            )}
          </div>
        ))
      )}
    </div>
  </section>
);

export default PortraitSegment;
