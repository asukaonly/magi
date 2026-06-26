import { Brain, Heart, Network, Wrench } from 'lucide-react';
import type { ChatPortraitObservation } from '@/api/modules/memoryPortrait';
import { cn } from '@/lib/utils';

// Icon stays as a subtle visual differentiator across kinds so users can
// scan multiple cards quickly, but the kind name itself is internal
// architecture (L2 assertion / L3 reflection / L4 procedure) — never
// shown to users.
const KIND_ICON = {
  reflection: Brain,
  assertion: Heart,
  relationship: Network,
  procedure: Wrench,
} as const;

const KIND_ICON_TINT: Record<ChatPortraitObservation['kind'], string> = {
  reflection: 'text-amber-600/70',
  assertion: 'text-rose-500/70',
  relationship: 'text-cyan-600/70',
  procedure: 'text-emerald-600/70',
};

export const PortraitCard = ({ observation }: { observation: ChatPortraitObservation }) => {
  const Icon = KIND_ICON[observation.kind];
  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border/45 bg-background/60 px-3 py-3 text-[13px] leading-[1.7]"
      data-testid="portrait-card"
    >
      <div className="flex items-start gap-2">
        <Icon
          className={cn('mt-1 h-3.5 w-3.5 shrink-0', KIND_ICON_TINT[observation.kind])}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1 text-foreground/90">{observation.text}</div>
      </div>
      {observation.basis_summary ? (
        <div className="pl-[22px] text-[11px] italic text-muted-foreground/70">
          {observation.basis_summary}
        </div>
      ) : null}
    </div>
  );
};
