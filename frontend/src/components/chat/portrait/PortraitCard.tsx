import { useTranslation } from 'react-i18next';
import { Brain, Heart, Network, Wrench } from 'lucide-react';
import type { PortraitObservation } from '@/api/modules/memoryPortrait';

const KIND_ICON = {
  reflection: Brain,
  assertion: Heart,
  relationship: Network,
  procedure: Wrench,
} as const;

const KIND_LABEL_KEY: Record<PortraitObservation['kind'], string> = {
  reflection: 'chat.portrait.kinds.reflection',
  assertion: 'chat.portrait.kinds.assertion',
  relationship: 'chat.portrait.kinds.relationship',
  procedure: 'chat.portrait.kinds.procedure',
};

export const PortraitCard = ({ observation }: { observation: PortraitObservation }) => {
  const { t } = useTranslation('app');
  const Icon = KIND_ICON[observation.kind];
  const kindLabel = t(KIND_LABEL_KEY[observation.kind]);
  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-border/45 bg-background/60 px-3 py-2.5 text-[12.5px] leading-5"
      data-testid="portrait-card"
    >
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{kindLabel}</span>
      </div>
      <div className="text-foreground/90">{observation.text}</div>
      {observation.basis_summary ? (
        <div className="font-mono text-[10px] text-muted-foreground/70">
          {observation.basis_summary}
        </div>
      ) : null}
    </div>
  );
};
