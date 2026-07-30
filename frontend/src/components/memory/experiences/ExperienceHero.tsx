import type { ReactNode } from 'react';
import { Quote } from 'lucide-react';
import { ProtectedImage } from '@/components/media/ProtectedImage';
import { cn } from '@/lib/utils';

export function ExperienceHero({
  coverUrl,
  title,
  eyebrow,
  topContent,
  actions,
  metadata,
  recapLabel,
  recap,
  titleLevel = 1,
  variant = 'sheet',
  className,
}: {
  coverUrl?: string | null;
  title: string;
  eyebrow?: ReactNode;
  topContent?: ReactNode;
  actions?: ReactNode;
  metadata?: ReactNode;
  recapLabel: ReactNode;
  recap: ReactNode;
  titleLevel?: 1 | 2;
  variant?: 'sheet' | 'inline';
  className?: string;
}) {
  const isInline = variant === 'inline';
  const TitleTag = titleLevel === 1 ? 'h1' : 'h2';

  return (
    <header
      data-testid="experience-cover-hero"
      className={cn(
        'relative isolate min-h-[360px] overflow-hidden rounded-xl bg-[hsl(var(--memory-panel-elevated))] bg-cover bg-center ring-1 ring-inset ring-[hsl(var(--memory-border)/0.22)]',
        !isInline && 'shadow-[0_14px_42px_hsl(var(--memory-title)/0.055)]',
        className,
      )}
    >
      {coverUrl ? (
        <ProtectedImage
          src={coverUrl}
          alt=""
          eager
          aria-hidden="true"
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : null}
      {!coverUrl ? (
        <div className="absolute inset-0 bg-[linear-gradient(135deg,hsl(var(--memory-panel-elevated)),hsl(var(--memory-accent-soft)/0.42))]" />
      ) : null}
      <div className="absolute inset-0 bg-[linear-gradient(90deg,hsl(var(--memory-panel-elevated)/0.94)_0%,hsl(var(--memory-panel-elevated)/0.82)_42%,hsl(var(--memory-panel-elevated)/0.18)_100%)]" />
      <div className="absolute inset-x-0 bottom-0 h-2/3 bg-[linear-gradient(0deg,hsl(var(--memory-panel-elevated)/0.88),transparent)]" />

      <div className="relative z-10 flex min-h-[360px] flex-col px-6 py-6 md:px-10 md:py-8">
        {(topContent || actions) ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 text-xs text-[hsl(var(--memory-muted))]">{topContent}</div>
            {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
          </div>
        ) : null}

        <div className="flex max-w-3xl flex-1 flex-col justify-center py-5">
          {eyebrow ? (
            <div className="text-xs font-semibold text-[hsl(var(--memory-accent))]">{eyebrow}</div>
          ) : null}
          <TitleTag className={cn(
            'max-w-3xl break-words font-semibold leading-tight text-[hsl(var(--memory-title))]',
            eyebrow ? 'mt-2' : 'mt-1',
            isInline ? 'text-2xl' : 'text-3xl md:text-[2.28rem]',
          )}>
            {title}
          </TitleTag>

          {metadata ? (
            <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-[hsl(var(--memory-muted))]">
              {metadata}
            </div>
          ) : null}

          <div className="mt-7 max-w-2xl border-l-2 border-[hsl(var(--memory-accent)/0.38)] bg-[hsl(var(--memory-panel-elevated)/0.5)] px-5 py-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
              <Quote className="h-4 w-4 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
              {recapLabel}
            </div>
            <div className="mt-3 whitespace-pre-wrap break-words text-base leading-8 text-[hsl(var(--memory-body))]">
              {recap}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

export default ExperienceHero;
