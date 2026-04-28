import type { ReactNode } from 'react';

import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

export function SettingsSectionShell({
  children,
}: {
  children: ReactNode;
}) {
  return <div className="space-y-8">{children}</div>;
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
      <div className="space-y-1.5">
        <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">{title}</h3>
        {description ? <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{description}</p> : null}
      </div>
      <div className={cn('space-y-3', contentClassName)}>{children}</div>
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
    <section className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="space-y-1">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs leading-6 text-muted-foreground">{description}</div>
        {hint ? <p className={cn('text-xs leading-6 text-muted-foreground', hintClassName)}>{hint}</p> : null}
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