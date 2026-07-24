import { type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  MEMORY_GHOST_ACTION_CLASS,
  MEMORY_PRIMARY_ACTION_CLASS,
} from '@/components/memory/memoryActionStyles';

const TONE_DOT_CLASS: Record<'amber' | 'green' | 'blue', string> = {
  amber: 'bg-amber-500/80 dark:bg-amber-400/80',
  green: 'bg-emerald-500/80 dark:bg-emerald-400/80',
  blue: 'bg-sky-500/80 dark:bg-sky-400/80',
};

export function PendingSection({
  title,
  description,
  count,
  tone,
  children,
}: {
  title: string;
  description: string;
  count: number;
  tone: 'amber' | 'green' | 'blue';
  children: ReactNode;
}) {
  if (count === 0) {
    return null;
  }
  return (
    <section>
      <header className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-[13px] font-semibold text-[hsl(var(--memory-title))]">
            <span aria-hidden="true" className={cn('h-1.5 w-1.5 shrink-0 rounded-full', TONE_DOT_CLASS[tone])} />
            {title}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">{description}</p>
        </div>
        <span className="shrink-0 text-xs tabular-nums text-[hsl(var(--memory-muted))]">{count}</span>
      </header>
      <div>{children}</div>
    </section>
  );
}

export function PendingCard({
  testId,
  label,
  title,
  body,
  meta,
  actions,
}: {
  testId: string;
  label?: string;
  title: string;
  body: string;
  meta: string;
  actions: ReactNode;
}) {
  return (
    <article
      data-testid={testId}
      className="grid gap-3 py-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-8"
    >
      <div className="min-w-0">
        {(label || meta) ? (
          <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
            {label ? <span>{label}</span> : null}
            {label && meta ? <span aria-hidden="true">·</span> : null}
            {meta ? <span>{meta}</span> : null}
          </div>
        ) : null}
        <h3 className="break-words text-[15px] font-medium leading-7 text-[hsl(var(--memory-title))]">{title}</h3>
        {body ? <p className="mt-1 line-clamp-2 text-[13px] leading-6 text-[hsl(var(--memory-body))]">{body}</p> : null}
      </div>
      <div className="md:justify-self-end">{actions}</div>
    </article>
  );
}

export function ReviewActions({
  busy,
  confirmLabel,
  rejectLabel,
  onConfirm,
  onReject,
}: {
  busy: boolean;
  confirmLabel: string;
  rejectLabel: string;
  onConfirm: () => void;
  onReject: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={MEMORY_PRIMARY_ACTION_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        {confirmLabel}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={MEMORY_GHOST_ACTION_CLASS}
        disabled={busy}
        onClick={onReject}
      >
        {rejectLabel}
      </Button>
    </div>
  );
}

export function ConflictActions({
  busy,
  onConfirm,
  onReject,
}: {
  busy: boolean;
  onConfirm: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation('app');
  return (
    <div className="flex flex-wrap items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={MEMORY_PRIMARY_ACTION_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        {t('memory.pending.actions.acceptConflict')}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={MEMORY_GHOST_ACTION_CLASS}
        disabled={busy}
        onClick={onReject}
      >
        {t('memory.pending.actions.keepExisting')}
      </Button>
    </div>
  );
}
