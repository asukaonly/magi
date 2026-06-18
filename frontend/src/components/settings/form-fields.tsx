/**
 * Reusable form field components for settings page.
 */

import React from 'react';

import { SelectField as BaseSelectField } from '@/components/config-forms/fields';
import { cn } from '@/lib/utils';

// ============================================================================
// Types
// ============================================================================

export interface SelectOption {
  label: string;
  value: string;
}

// ============================================================================
// LabeledSelectField
// ============================================================================

export interface LabeledSelectFieldProps {
  label: string;
  ariaLabel?: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
}

export const LabeledSelectField: React.FC<LabeledSelectFieldProps> = ({
  label,
  ariaLabel,
  value,
  options,
  onChange,
  className,
  triggerClassName,
  menuClassName,
}) => (
  <label className={cn('space-y-2.5', className)}>
    {label ? <span className="text-sm font-semibold leading-6 text-foreground">{label}</span> : null}
    <BaseSelectField
      value={value}
      onChange={onChange}
      options={options}
      allowEmpty={false}
      ariaLabel={ariaLabel}
      triggerClassName={cn(
        'h-11 rounded-lg border-transparent bg-[hsl(var(--settings-shell-elevated)/0.78)] px-4 text-[15px] text-foreground shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.28)]',
        'transition-[background-color,box-shadow,color] duration-200 hover:bg-[hsl(var(--settings-shell-elevated)/0.96)] hover:shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.44)]',
        'focus-visible:ring-2 focus-visible:ring-ring/25 focus-visible:ring-offset-0',
        triggerClassName
      )}
      menuClassName={cn(
        'rounded-lg border-transparent bg-[hsl(var(--settings-shell-elevated))] shadow-[0_18px_42px_hsl(var(--foreground)/0.12),inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.24)]',
        menuClassName
      )}
    />
  </label>
);

// ============================================================================
// NumberField
// ============================================================================

export interface NumberFieldProps {
  label: string;
  value: number | undefined;
  min?: number;
  max?: number;
  step?: number;
  onChange: (value: number) => void;
}

export const NumberField: React.FC<NumberFieldProps> = ({
  label,
  value,
  min,
  max,
  step,
  onChange,
}) => (
  <label className="space-y-2.5">
    <span className="text-sm font-semibold leading-6 text-foreground">{label}</span>
    <input
      className="h-11 w-full rounded-lg border-transparent bg-[hsl(var(--settings-shell-elevated)/0.78)] px-4 text-sm text-foreground shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.28)] transition-[background-color,box-shadow,color] duration-200 hover:bg-[hsl(var(--settings-shell-elevated)/0.96)] hover:shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.44)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25"
      type="number"
      min={min}
      max={max}
      step={step}
      value={value ?? ''}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  </label>
);
