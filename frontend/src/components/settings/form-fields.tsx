/**
 * Reusable form field components for settings page.
 */

import React from 'react';

import { SelectField as BaseSelectField } from '@/components/config-forms/fields';

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
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}

export const LabeledSelectField: React.FC<LabeledSelectFieldProps> = ({
  label,
  value,
  options,
  onChange,
}) => (
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <BaseSelectField value={value} onChange={onChange} options={options} allowEmpty={false} />
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
  <label className="space-y-2">
    <span className="text-sm font-medium">{label}</span>
    <input
      className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
      type="number"
      min={min}
      max={max}
      step={step}
      value={value ?? ''}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  </label>
);
