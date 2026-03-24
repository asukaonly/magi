import type { FC } from 'react';
import { StatisticsPageFrame } from './StatisticsPageFrame';

const ribbonItems = [
  'Total Tokens',
  'Total Cost',
  'Avg Latency',
  'Avg TTFT',
  'Success Rate',
];

export const LLMStatisticsSection: FC = () => (
  <div data-testid="llm-statistics-section" className="h-full min-h-0">
    <StatisticsPageFrame
      toolbar={(
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="rounded-full border border-[hsl(var(--settings-subnav-border)/0.9)] px-3 py-1.5 text-sm font-medium text-foreground">
              7D
            </button>
            <button type="button" className="rounded-full border border-[hsl(var(--settings-subnav-border)/0.72)] px-3 py-1.5 text-sm text-[hsl(var(--settings-nav-foreground))]">
              30D
            </button>
          </div>
          <div className="text-sm text-muted-foreground">updated just now</div>
        </>
      )}
      signalRibbon={ribbonItems.map((item) => (
        <div key={item} className="space-y-2">
          <div className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground">{item}</div>
          <div className="text-2xl font-semibold text-foreground">--</div>
        </div>
      ))}
      mainCanvas={(
        <div className="space-y-4 rounded-[1.5rem] border border-[hsl(var(--settings-subnav-border)/0.62)] bg-[hsl(var(--settings-shell-elevated)/0.34)] p-5">
          <div className="text-sm font-medium text-foreground">Primary trend canvas</div>
          <div className="h-56 rounded-[1.2rem] bg-[hsl(var(--settings-shell-elevated)/0.42)]" />
        </div>
      )}
      secondary={(
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-[1.3rem] border border-[hsl(var(--settings-subnav-border)/0.52)] p-4 text-sm text-muted-foreground">
            Secondary analysis A
          </div>
          <div className="rounded-[1.3rem] border border-[hsl(var(--settings-subnav-border)/0.52)] p-4 text-sm text-muted-foreground">
            Secondary analysis B
          </div>
        </div>
      )}
      summaryRail={(
        <>
          <div className="text-sm font-medium text-foreground">Health summary</div>
          <div className="text-sm leading-6 text-muted-foreground">Key runtime and usage changes will be summarized here.</div>
        </>
      )}
    />
  </div>
);

export default LLMStatisticsSection;
