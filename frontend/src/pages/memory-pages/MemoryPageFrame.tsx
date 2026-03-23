import type { ReactNode } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface MemoryPageFrameProps {
  title: string;
  description: string;
  filters?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export const MemoryPageFrame = ({
  title,
  description,
  filters,
  actions,
  children,
  className,
}: MemoryPageFrameProps) => (
  <div
    data-testid="memory-theme-root"
    className={cn('memory-theme-surface mx-auto flex h-full max-w-[1380px] flex-col gap-5 overflow-y-auto px-6 py-6', className)}
  >
    <section
      data-testid="memory-page-header"
      className="rounded-[1.6rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.94)] px-5 py-5 shadow-[0_12px_28px_-26px_hsl(var(--memory-shadow)/0.35)]"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-1.5">
          <h1 className="text-[1.85rem] font-semibold tracking-[-0.03em] text-[hsl(var(--memory-title))]">{title}</h1>
          <p className="max-w-3xl text-sm leading-6 text-[hsl(var(--memory-body))]">{description}</p>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2 lg:justify-end">{actions}</div> : null}
      </div>

      {filters ? (
        <div
          data-testid="memory-page-filters"
          className="mt-4 border-t border-[hsl(var(--memory-divider))] pt-4"
        >
          {filters}
        </div>
      ) : null}
    </section>

    <div className="pb-5">{children}</div>
  </div>
);

export const MemoryHeroStat = ({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  tone?: 'default' | 'accent';
}) => (
  <div
    className={cn(
      'rounded-[1.1rem] border px-4 py-3 shadow-[0_10px_18px_-20px_hsl(var(--memory-shadow)/0.28)]',
      tone === 'accent'
        ? 'border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-accent-soft)/0.95)]'
        : 'border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.92)]'
    )}
  >
    <div className="text-xs text-[hsl(var(--memory-muted))]">{label}</div>
    <div className="mt-1.5 text-xl font-semibold text-[hsl(var(--memory-title))]">{value}</div>
  </div>
);

export const MemoryWorkspacePanel = ({
  title,
  description,
  children,
  className,
  testId,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  testId?: string;
}) => (
  <Card
    data-testid={testId}
    className={cn(
      'rounded-[1.35rem] border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.95)] shadow-[0_12px_24px_-24px_hsl(var(--memory-shadow)/0.28)]',
      className
    )}
  >
    <CardHeader className="pb-3">
      <CardTitle className="text-base text-[hsl(var(--memory-title))]">{title}</CardTitle>
      {description ? <p className="text-sm leading-6 text-[hsl(var(--memory-body))]">{description}</p> : null}
    </CardHeader>
    <CardContent>{children}</CardContent>
  </Card>
);

export const MemoryTag = ({ children }: { children: ReactNode }) => (
  <span className="inline-flex items-center rounded-full border border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.95)] px-3 py-1 text-xs text-[hsl(var(--memory-body))]">
    {children}
  </span>
);

export const MEMORY_FILTER_INPUT_CLASS =
  'h-10 rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] placeholder:text-[hsl(var(--memory-input-placeholder))] focus-visible:ring-[hsl(var(--memory-accent)/0.42)]';

export const MEMORY_FILTER_SELECT_CLASS =
  'flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] shadow-sm outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]';

export const MEMORY_ACTION_BUTTON_CLASS =
  'rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]';

export const MEMORY_INFO_PANEL_CLASS =
  'rounded-[1.25rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.88)] px-4 py-3 text-sm text-[hsl(var(--memory-body))]';

export const MEMORY_EMPTY_PANEL_CLASS =
  'rounded-[1.35rem] border border-dashed border-[hsl(var(--memory-empty-border))] bg-[hsl(var(--memory-empty-bg)/0.86)] p-4 text-sm leading-6 text-[hsl(var(--memory-body))]';

export const MEMORY_SECTION_CARD_CLASS =
  'rounded-[1.35rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.88)] p-4';

export const MEMORY_INTERACTIVE_CARD_CLASS =
  'group flex items-center justify-between rounded-[1.35rem] border border-[hsl(var(--memory-border))] bg-[hsl(var(--memory-panel-elevated)/0.88)] px-4 py-3 transition-all duration-200 hover:-translate-y-0.5 hover:border-[hsl(var(--memory-accent)/0.45)] hover:bg-[hsl(var(--memory-panel-elevated))]';

export default MemoryPageFrame;
