import { cn } from '@/lib/utils';

interface OptionItem {
  label: string;
  value: string;
}

export function SelectField({
  value,
  onChange,
  options,
  placeholder = '请选择',
  disabled = false,
  allowEmpty = true,
  className,
}: {
  value?: string;
  onChange?: (value: string) => void;
  options: OptionItem[];
  placeholder?: string;
  disabled?: boolean;
  allowEmpty?: boolean;
  className?: string;
}): JSX.Element {
  return (
    <select
      className={cn(
        'h-10 w-full rounded-md border border-input bg-background px-3 text-sm',
        disabled && 'cursor-not-allowed opacity-50',
        className
      )}
      value={value ?? ''}
      onChange={(event) => onChange?.(event.target.value)}
      disabled={disabled}
    >
      {allowEmpty ? <option value="">{placeholder}</option> : null}
      {options.map((item) => (
        <option key={item.value} value={item.value}>
          {item.label}
        </option>
      ))}
    </select>
  );
}

export function SwitchField({
  checked,
  onChange,
  disabled = false,
}: {
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
}): JSX.Element {
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={!!checked}
        onChange={(event) => onChange?.(event.target.checked)}
        disabled={disabled}
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
