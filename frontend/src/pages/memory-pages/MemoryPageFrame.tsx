import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface MemoryPageFrameProps {
  title: string;
  description: string;
  filters?: ReactNode;
  actions?: ReactNode;
  headerMeta?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  hideHeader?: boolean;
  scrollable?: boolean;
}

export const MemoryPageFrame = ({
  title,
  description,
  filters,
  actions,
  headerMeta,
  children,
  className,
  contentClassName,
  hideHeader = false,
  scrollable = true,
}: MemoryPageFrameProps) => (
  <div
    data-testid="memory-theme-root"
    className={cn(
      'memory-theme-surface mx-auto flex h-full max-w-[1380px] flex-col gap-4 px-4 py-4',
      scrollable ? 'overflow-y-auto' : 'overflow-hidden',
      className
    )}
  >
    {!hideHeader ? (
      <section
        data-testid="memory-page-header"
        className="rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-4 py-4"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-1.5">
            <h1 className="text-[1.85rem] font-semibold tracking-[-0.03em] text-[hsl(var(--memory-title))]">{title}</h1>
            <p className="max-w-3xl text-sm leading-6 text-[hsl(var(--memory-body))]">{description}</p>
          </div>
          {actions || headerMeta ? (
            <div className="flex flex-col gap-2 lg:min-w-fit lg:self-stretch lg:items-end lg:justify-between">
              {actions ? <div className="flex flex-wrap items-center gap-2 lg:justify-end">{actions}</div> : null}
              {headerMeta ? <div className="max-w-full">{headerMeta}</div> : null}
            </div>
          ) : null}
        </div>

        {filters ? (
          <div
            data-testid="memory-page-filters"
            className="mt-3 border-t border-[hsl(var(--memory-divider)/0.68)] pt-3"
          >
            {filters}
          </div>
        ) : null}
      </section>
    ) : null}

    <div className={cn('pb-5', contentClassName)}>{children}</div>
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
      'rounded-xl border px-4 py-3',
      tone === 'accent'
        ? 'border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-accent-soft)/0.7)]'
        : 'border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.68)]'
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
  <section
    data-testid={testId}
    className={cn(
      'rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.72)] px-5 py-4',
      className
    )}
  >
    <div className="space-y-1.5">
      <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
      {description ? <p className="text-sm leading-6 text-[hsl(var(--memory-body))]">{description}</p> : null}
    </div>
    <div className={cn(description ? 'mt-4' : 'mt-3')}>{children}</div>
  </section>
);

export const MemoryTag = ({ children }: { children: ReactNode }) => (
  <span className="inline-flex items-center rounded-md bg-[hsl(var(--memory-panel-subtle)/0.76)] px-2.5 py-1 text-xs text-[hsl(var(--memory-body))]">
    {children}
  </span>
);

export const MEMORY_FILTER_INPUT_CLASS =
  'h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 text-sm text-[hsl(var(--memory-title))] placeholder:text-[hsl(var(--memory-input-placeholder))] placeholder:text-sm focus-visible:ring-[hsl(var(--memory-accent)/0.12)]';

export const MEMORY_FILTER_SELECT_CLASS =
  'flex h-9 w-full rounded-sm border border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.22)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.24)]';

export const MEMORY_ACTION_BUTTON_CLASS =
  'h-9 rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] px-4 text-sm text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle)/0.82)]';

export const MEMORY_INFO_PANEL_CLASS =
  'rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.38)] px-4 py-3 text-sm leading-6 text-[hsl(var(--memory-body))] shadow-[inset_0_0_0_1px_hsl(var(--memory-divider)/0.22)]';

export const MEMORY_EMPTY_PANEL_CLASS =
  'rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.32)] px-4 py-3 text-sm leading-6 text-[hsl(var(--memory-muted))] shadow-[inset_0_0_0_1px_hsl(var(--memory-divider)/0.2)]';

export const MEMORY_SECTION_CARD_CLASS =
  'rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.68)] p-4';

export const MEMORY_SECTION_SURFACE_CLASS =
  'rounded-2xl bg-[hsl(var(--memory-panel-elevated)/0.58)] px-5 py-5 shadow-[0_14px_36px_hsl(var(--memory-shadow)/0.035)] sm:px-6';

export const MEMORY_INTERACTIVE_CARD_CLASS =
  'group flex items-center justify-between rounded-2xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-4 py-3 transition-colors duration-200 hover:border-[hsl(var(--memory-accent)/0.28)] hover:bg-[hsl(var(--memory-panel-elevated)/0.86)]';

export default MemoryPageFrame;
