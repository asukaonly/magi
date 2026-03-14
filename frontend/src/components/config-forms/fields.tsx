import { cn } from '@/lib/utils';
import { Check, ChevronDown } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';

interface OptionItem {
  label: string;
  value: string;
  disabled?: boolean;
}

export function SelectField({
  value,
  onChange,
  options,
  placeholder = '请选择',
  disabled = false,
  allowEmpty = true,
  className,
  triggerClassName,
  menuClassName,
}: {
  value?: string;
  onChange?: (value: string) => void;
  options: OptionItem[];
  placeholder?: string;
  disabled?: boolean;
  allowEmpty?: boolean;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  // Case-insensitive matching for selected option
  const selectedOption = options.find(
    (opt) => opt.value.toLowerCase() === (value || '').toLowerCase()
  );

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (optValue: string) => {
    onChange?.(optValue);
    setOpen(false);
  };

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className={cn(
          'flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm shadow-[0_1px_2px_rgba(15,23,42,0.05)]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-600/60',
          disabled && 'cursor-not-allowed opacity-50',
          !selectedOption && 'text-muted-foreground',
          triggerClassName
        )}
      >
        <span>{selectedOption?.label || placeholder}</span>
        <ChevronDown className="h-4 w-4 opacity-50" />
      </button>

      {open && (
        <div
          className={cn(
            'absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-background shadow-[0_12px_24px_rgba(15,23,42,0.08)]',
            menuClassName
          )}
        >
          {allowEmpty && (
            <button
              type="button"
              onClick={() => handleSelect('')}
              className="flex w-full items-center justify-between px-3 py-2 text-sm hover:bg-muted/50"
            >
              <span className="text-muted-foreground">{placeholder}</span>
              {!value && <Check className="h-4 w-4 text-primary-600" />}
            </button>
          )}
          {options.map((opt) => (
            <button
              type="button"
              key={opt.value}
              onClick={() => {
                if (!opt.disabled) {
                  handleSelect(opt.value);
                }
              }}
              disabled={opt.disabled}
              className={cn(
                'flex w-full items-center justify-between px-3 py-2 text-sm',
                opt.disabled
                  ? 'cursor-not-allowed text-muted-foreground/60'
                  : 'hover:bg-muted/50'
              )}
            >
              <span>{opt.label}</span>
              {value === opt.value && <Check className="h-4 w-4 text-primary-600" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

SelectField.displayName = 'Select';

export function SwitchField({
  checked,
  onChange,
  disabled = false,
  ariaLabel,
}: {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
}): JSX.Element {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={!!checked}
        onChange={(event) => onChange?.(event.target.checked)}
        disabled={disabled}
        aria-label={ariaLabel}
      />
      <span>{checked ? '已启用' : '已关闭'}</span>
    </label>
  );
}

export function CheckboxGroupField({
  options,
  value = [],
  onChange,
  disabled = false,
}: {
  options: OptionItem[];
  value?: string[];
  onChange?: (value: string[]) => void;
  disabled?: boolean;
}): JSX.Element {
  return (
    <div className="space-y-2">
      {options.map((item) => (
        <label key={item.value} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value.includes(item.value)}
            onChange={(event) => {
              const next = new Set(value);
              if (event.target.checked) next.add(item.value);
              else next.delete(item.value);
              onChange?.(Array.from(next));
            }}
            disabled={disabled}
          />
          <span>{item.label}</span>
        </label>
      ))}
    </div>
  );
}
