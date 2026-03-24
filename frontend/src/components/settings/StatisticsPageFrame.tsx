import type { FC, ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface StatisticsPageFrameProps {
  toolbar: ReactNode;
  signalRibbon: ReactNode;
  mainCanvas: ReactNode;
  summaryRail: ReactNode;
  secondary?: ReactNode;
  className?: string;
}

export const StatisticsPageFrame: FC<StatisticsPageFrameProps> = ({
  toolbar,
  signalRibbon,
  mainCanvas,
  summaryRail,
  secondary,
  className,
}) => (
  <div className={cn('flex h-full min-h-0 flex-col gap-6', className)}>
    <div
      data-testid="statistics-page-toolbar"
      className="flex flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--settings-subnav-border)/0.72)] pb-4"
    >
      {toolbar}
    </div>

    <div
      data-testid="statistics-page-signal-ribbon"
      className="grid gap-4 border-b border-[hsl(var(--settings-subnav-border)/0.56)] pb-4 md:grid-cols-4 xl:grid-cols-5"
    >
      {signalRibbon}
    </div>

    <div className="grid min-h-0 flex-1 gap-8 xl:grid-cols-[minmax(0,1.5fr)_300px]">
      <div className="min-h-0 space-y-6">
        <div data-testid="statistics-page-main-canvas">{mainCanvas}</div>
        {secondary ? <div>{secondary}</div> : null}
      </div>
      <aside data-testid="statistics-page-summary-rail" className="space-y-4 xl:border-l xl:border-[hsl(var(--settings-subnav-border)/0.56)] xl:pl-6">
        {summaryRail}
      </aside>
    </div>
  </div>
);

export default StatisticsPageFrame;
