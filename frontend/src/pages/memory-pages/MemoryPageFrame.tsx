import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface MemoryPageFrameProps {
  title: string;
  description: string;
  eyebrow?: string;
  heroStats?: ReactNode;
  heroAside?: ReactNode;
  filters?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export const MemoryPageFrame = ({
  title,
  description,
  eyebrow,
  heroStats,
  heroAside,
  filters,
  actions,
  children,
  className,
}: MemoryPageFrameProps) => {
  const { t } = useTranslation('app');

  return (
    <div className={cn('mx-auto flex h-full max-w-7xl flex-col gap-6 overflow-y-auto p-5', className)}>
      <section
        data-testid="memory-page-hero"
        className="relative overflow-hidden rounded-[2rem] border border-[#e7d6c7] bg-[linear-gradient(180deg,#fcf7f2_0%,#f6eee6_100%)] px-6 py-6 shadow-[0_12px_40px_-28px_rgba(124,88,58,0.45)]"
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.8),transparent_52%)]" />
        <div className="pointer-events-none absolute -right-8 top-6 h-28 w-28 rounded-full bg-[rgba(232,210,192,0.45)] blur-2xl" />
        <div className="relative grid gap-5 lg:grid-cols-[minmax(0,1.18fr)_minmax(280px,0.82fr)]">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-[#e6d7cb] bg-white/75 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-[#8b6f5a]">
              <Sparkles className="h-3.5 w-3.5" />
              {eyebrow || t('memory.title')}
            </div>
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-tight text-[#36261c] md:text-[2.15rem]">{title}</h1>
              <p className="max-w-3xl text-sm leading-6 text-[#6f5a4a]">{description}</p>
            </div>
            {heroStats ? <div className="space-y-3">{heroStats}</div> : null}
          </div>
          <div className="flex flex-col gap-3 lg:items-stretch lg:justify-between">
            {actions ? <div className="flex flex-wrap items-center justify-start gap-2 lg:justify-end">{actions}</div> : null}
            {heroAside ? (
              <div className="rounded-[1.5rem] border border-[#e6d8cc] bg-white/72 p-4 text-sm text-[#6f5a4a] shadow-[0_10px_30px_-24px_rgba(108,74,48,0.4)]">
                {heroAside}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      {filters ? (
        <Card className="rounded-[1.75rem] border-[#e7d8cd] bg-[rgba(255,252,248,0.92)] shadow-[0_12px_35px_-30px_rgba(120,88,59,0.45)]">
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[#463427]">{t('memory.filters.title')}</CardTitle>
          </CardHeader>
          <CardContent>{filters}</CardContent>
        </Card>
      ) : null}

      <div className="pb-5">{children}</div>
    </div>
  );
};

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
      'rounded-[1.35rem] border px-4 py-4 shadow-[0_10px_24px_-22px_rgba(100,70,46,0.35)]',
      tone === 'accent'
        ? 'border-[#ddc5b0] bg-[rgba(246,231,218,0.88)]'
        : 'border-[#eadccf] bg-[rgba(255,255,255,0.78)]'
    )}
  >
    <div className="text-[11px] uppercase tracking-[0.16em] text-[#8f7460]">{label}</div>
    <div className="mt-2 text-2xl font-semibold text-[#35261c]">{value}</div>
  </div>
);

export const MEMORY_FILTER_INPUT_CLASS =
  'h-11 rounded-2xl border-[#e4d3c5] bg-white/85 text-[#3f2d21] placeholder:text-[#a18976] focus-visible:ring-[#d2b79f]';

export const MEMORY_FILTER_SELECT_CLASS =
  'flex h-11 w-full rounded-2xl border border-[#e4d3c5] bg-white/85 px-3 py-2 text-sm text-[#3f2d21] shadow-sm outline-none focus:border-[#d5baa3] focus:ring-2 focus:ring-[#ebdacb]';

export default MemoryPageFrame;
