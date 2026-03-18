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
  <div className={cn('mx-auto flex h-full max-w-[1380px] flex-col gap-5 overflow-y-auto px-6 py-6', className)}>
    <section
      data-testid="memory-page-header"
      className="rounded-[1.6rem] border border-[#e6ddd4] bg-[rgba(255,253,250,0.92)] px-5 py-5 shadow-[0_12px_28px_-26px_rgba(94,68,46,0.35)]"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-1.5">
          <h1 className="text-[1.85rem] font-semibold tracking-[-0.03em] text-[#2f231b]">{title}</h1>
          <p className="max-w-3xl text-sm leading-6 text-[#685548]">{description}</p>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2 lg:justify-end">{actions}</div> : null}
      </div>

      {filters ? (
        <div
          data-testid="memory-page-filters"
          className="mt-4 border-t border-[#eee5dc] pt-4"
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
      'rounded-[1.1rem] border px-4 py-3 shadow-[0_10px_18px_-20px_rgba(100,70,46,0.28)]',
      tone === 'accent'
        ? 'border-[#dfcfbf] bg-[rgba(252,247,241,0.95)]'
        : 'border-[#ebe1d8] bg-[rgba(255,255,255,0.92)]'
    )}
  >
    <div className="text-xs text-[#7d6657]">{label}</div>
    <div className="mt-1.5 text-xl font-semibold text-[#33271f]">{value}</div>
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
      'rounded-[1.35rem] border-[#e8ddd4] bg-[rgba(255,253,250,0.95)] shadow-[0_12px_24px_-24px_rgba(99,71,48,0.28)]',
      className
    )}
  >
    <CardHeader className="pb-3">
      <CardTitle className="text-base text-[#443227]">{title}</CardTitle>
      {description ? <p className="text-sm leading-6 text-[#7a6352]">{description}</p> : null}
    </CardHeader>
    <CardContent>{children}</CardContent>
  </Card>
);

export const MemoryTag = ({ children }: { children: ReactNode }) => (
  <span className="inline-flex items-center rounded-full border border-[#e7dbd0] bg-white/95 px-3 py-1 text-xs text-[#6a5547]">
    {children}
  </span>
);

export const MEMORY_FILTER_INPUT_CLASS =
  'h-10 rounded-xl border-[#e3d9cf] bg-white text-[#3d2e23] placeholder:text-[#9d8878] focus-visible:ring-[#d5c0ac]';

export const MEMORY_FILTER_SELECT_CLASS =
  'flex h-10 w-full rounded-xl border border-[#e3d9cf] bg-white px-3 py-2 text-sm text-[#3d2e23] shadow-sm outline-none focus:border-[#d4beaa] focus:ring-2 focus:ring-[#eadccf]';

export default MemoryPageFrame;
