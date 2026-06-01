import { useEffect } from 'react';
import { useChatShellStore } from '@/stores';
import { MemoryPortraitRail } from '../MemoryPortraitRail';

export interface PortraitFloaterProps {
  sessionId: string;
  userId: string;
  personaId: string;
}

export const PortraitFloater = (props: PortraitFloaterProps) => {
  const setOpen = useChatShellStore((s) => s.setPortraitRailOpen);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [setOpen]);

  return (
    <div
      className="pointer-events-auto absolute right-3 top-12 z-30 max-h-[70vh] w-[320px] overflow-hidden rounded-lg border border-border/60 bg-background shadow-lg"
      data-testid="portrait-floater"
    >
      <MemoryPortraitRail {...props} />
    </div>
  );
};
