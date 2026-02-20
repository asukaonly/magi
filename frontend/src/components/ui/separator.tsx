import { cn } from '@/lib/utils';

function Separator({ className, vertical = false }: { className?: string; vertical?: boolean }): JSX.Element {
  return (
    <div
      className={cn(vertical ? 'h-full w-px bg-border' : 'h-px w-full bg-border', className)}
      role="separator"
      aria-orientation={vertical ? 'vertical' : 'horizontal'}
    />
  );
}

export { Separator };
