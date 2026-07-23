import { type ReactNode } from 'react';
import { Check, Loader2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  MEMORY_GHOST_ACTION_CLASS,
  MEMORY_PRIMARY_ACTION_CLASS,
} from '../MemoryPageFrame';

export function PendingSection({
  title,
  description,
  icon,
  count,
  tone,
  children,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  count: number;
  tone: 'amber' | 'green' | 'blue';
  children: ReactNode;
}) {
  if (count === 0) {
    return null;
  }
  return (
    <section className="rounded-mem-lg bg-[hsl(var(--memory-panel-elevated)/0.6)] px-5 py-5 shadow-[0_14px_36px_hsl(var(--memory-shadow)/0.035)] sm:px-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-mem-sm',
              tone === 'amber' && 'bg-amber-500/10 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300',
              tone === 'green' && 'bg-emerald-500/10 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300',
              tone === 'blue' && 'bg-sky-500/10 text-sky-700 dark:bg-sky-400/15 dark:text-sky-300'
            )}
          >
            {icon}
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
            <p className="mt-0.5 truncate text-xs leading-5 text-[hsl(var(--memory-muted))]">{description}</p>
          </div>
        </div>
        <span className="shrink-0 text-xs tabular-nums text-[hsl(var(--memory-muted))]">{count}</span>
      </div>
      <div className="mt-2">{children}</div>
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
      className="grid gap-3 py-4 first:pt-3 last:pb-1 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
    >
      <div className="min-w-0">
        {(label || meta) ? (
          <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
            {label ? <span className="font-medium text-[hsl(var(--memory-body))]">{label}</span> : null}
            {label && meta ? <span aria-hidden="true">·</span> : null}
            {meta ? <span>{meta}</span> : null}
          </div>
        ) : null}
        <h3 className="break-words text-sm font-medium leading-7 text-[hsl(var(--memory-title))]">{title}</h3>
        {body ? <p className="mt-1 line-clamp-2 text-sm leading-7 text-[hsl(var(--memory-body))]">{body}</p> : null}
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
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={MEMORY_PRIMARY_ACTION_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
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
        <X className="h-3.5 w-3.5" />
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
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={MEMORY_PRIMARY_ACTION_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
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
        <X className="h-3.5 w-3.5" />
        {t('memory.pending.actions.keepExisting')}
      </Button>
    </div>
  );
}
