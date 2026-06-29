import { type ReactNode } from 'react';
import { Check, Loader2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { MEMORY_ACTION_BUTTON_CLASS } from '../MemoryPageFrame';

const MEMORY_REVIEW_BUTTON_CLASS = cn(
  MEMORY_ACTION_BUTTON_CLASS,
  'bg-[hsl(var(--memory-panel-elevated))] text-[hsl(var(--memory-title))]',
  'shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.62)]',
  'hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))]',
  'hover:shadow-[inset_0_0_0_1px_hsl(var(--memory-border)/0.78)]'
);

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
    <section className="overflow-hidden rounded-xl border border-[hsl(var(--memory-border)/0.56)] bg-[hsl(var(--memory-panel-elevated)/0.7)]">
      <div className="flex items-center justify-between gap-4 border-b border-[hsl(var(--memory-divider)/0.56)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
              tone === 'amber' && 'bg-amber-100/70 text-amber-700',
              tone === 'green' && 'bg-emerald-100/70 text-emerald-700',
              tone === 'blue' && 'bg-sky-100/75 text-sky-700'
            )}
          >
            {icon}
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
            <p className="mt-0.5 truncate text-xs text-[hsl(var(--memory-muted))]">{description}</p>
          </div>
        </div>
        <span className="shrink-0 text-xs text-[hsl(var(--memory-muted))]">{count}</span>
      </div>
      <div className="divide-y divide-[hsl(var(--memory-divider)/0.54)]">{children}</div>
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
      className="grid gap-3 px-4 py-3.5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
    >
      <div className="min-w-0">
        {(label || meta) ? (
          <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[hsl(var(--memory-muted))]">
            {label ? <span className="font-medium text-[hsl(var(--memory-body))]">{label}</span> : null}
            {label && meta ? <span aria-hidden="true">·</span> : null}
            {meta ? <span>{meta}</span> : null}
          </div>
        ) : null}
        <h3 className="break-words text-sm font-semibold leading-6 text-[hsl(var(--memory-title))]">{title}</h3>
        {body ? <p className="mt-1 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">{body}</p> : null}
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
        variant="outline"
        size="sm"
        className={MEMORY_REVIEW_BUTTON_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        {confirmLabel}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={MEMORY_REVIEW_BUTTON_CLASS}
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
        size="sm"
        className={MEMORY_ACTION_BUTTON_CLASS}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        {t('memory.pending.actions.acceptConflict')}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={MEMORY_ACTION_BUTTON_CLASS}
        disabled={busy}
        onClick={onReject}
      >
        <X className="h-3.5 w-3.5" />
        {t('memory.pending.actions.keepExisting')}
      </Button>
    </div>
  );
}
