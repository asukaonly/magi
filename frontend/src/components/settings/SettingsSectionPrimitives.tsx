import type { ReactNode } from 'react';

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
