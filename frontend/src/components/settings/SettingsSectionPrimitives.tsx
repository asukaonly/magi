import type { ReactNode } from 'react';
import { Store, type LucideIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

export function SettingsSectionShell({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn('mx-auto w-full max-w-[980px] space-y-10', className)}>{children}</div>;
}

export function SettingsGroup({
  title,
  description,
  contentClassName,
  children,
}: {
  title: string;
  description?: string;
  contentClassName?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="space-y-2">
        <h3 className="text-[15px] font-semibold leading-6 text-foreground">{title}</h3>
        {description ? <p className="max-w-3xl text-sm leading-7 text-muted-foreground">{description}</p> : null}
      </div>
      <div className={cn('space-y-3.5', contentClassName)}>{children}</div>
    </section>
  );
}

export function SettingsEmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  testId,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      className="rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.48)] px-5 py-5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.2)]"
    >
      <div className="flex max-w-2xl items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.13)]"
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 space-y-2">
          <div className="space-y-1">
            <h3 className="text-sm font-semibold leading-6 text-foreground">{title}</h3>
            <p className="text-sm leading-6 text-muted-foreground">{description}</p>
          </div>
          {actionLabel && onAction ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onAction}
              className="h-9 rounded-md border-transparent bg-background/64 px-3.5 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.34)] transition-[background-color,box-shadow,color] duration-200 hover:bg-[hsl(var(--settings-nav-hover)/0.72)] hover:text-foreground"
            >
              <Store className="mr-1.5 h-4 w-4" />
              {actionLabel}
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

export function SettingsSwitchRow({
  title,
  description,
  checked,
  onCheckedChange,
  ariaLabel,
  disabled = false,
  hint,
  hintClassName,
}: {
  title: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  ariaLabel: string;
  disabled?: boolean;
  hint?: string;
  hintClassName?: string;
}) {
  return (
    <section className="grid gap-4 rounded-lg px-1 py-2.5 transition-colors duration-200 hover:bg-[hsl(var(--settings-shell-elevated)/0.36)] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="space-y-1">
        <div className="text-sm font-medium leading-6 text-foreground">{title}</div>
        <div className="text-sm leading-6 text-muted-foreground">{description}</div>
        {hint ? <p className={cn('text-sm leading-6 text-muted-foreground', hintClassName)}>{hint}</p> : null}
      </div>
      <div className="flex justify-start sm:justify-end">
        <Switch
          aria-label={ariaLabel}
          checked={checked}
          disabled={disabled}
          onCheckedChange={onCheckedChange}
        />
      </div>
    </section>
  );
}
